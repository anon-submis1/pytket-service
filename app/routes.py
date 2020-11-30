# ******************************************************************************
#  Copyright (c) 2020 University of Stuttgart
#
#  See the NOTICE file(s) distributed with this work for additional
#  information regarding copyright ownership.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# ******************************************************************************

from app import app, implementation_handler, db, parameters
from app.result_model import Result
from app.tket_handler import get_backend, pretranspile_circuit, is_tk_circuit, setup_credentials, tket_transpile_circuit, UnsupportedGateException, TooManyQubitsException
from qiskit import IBMQ

from flask import jsonify, abort, request
import logging
import json
import re


@app.route('/pytket-service/api/v1.0/transpile', methods=['POST'])
def transpile_circuit():
    """Get implementation from URL. Pass input into implementation. Generate and transpile circuit
    and return depth and width."""

    if not request.json or not 'impl-url' in request.json or not 'qpu-name' in request.json:
        abort(400)

    impl_url = request.json['impl-url']
    provider = request.json["provider"]
    sdk = request.json["sdk"]
    qpu_name = request.json['qpu-name']
    input_params = request.json.get('input-params', "")
    input_params = parameters.ParameterDictionary(input_params)

    short_impl_name = re.match(".*/(?P<file>.*\\.py)", impl_url).group('file')

    # setup the SDK credentials first
    setup_credentials(sdk, **input_params)

    # Download and execute the implementation
    try:
        circuit = implementation_handler.prepare_code_from_url(impl_url, input_params)
        if not circuit:
            app.logger.warn(f"{short_impl_name} not found.")
            abort(404)

    except Exception as e:
        app.logger.info(f"Transpile {short_impl_name} for {qpu_name}: {str(e)}")
        return jsonify({'error': str(e)}), 200

    # Identify the backend given provider and qpu name
    backend = get_backend(provider, qpu_name)

    if not backend:
        app.logger.warn(f"{qpu_name} not found.")
        abort(404)

    precompiled_circuit = False
    while not is_tk_circuit(circuit):

        try:
            circuit = tket_transpile_circuit(circuit,
                                             sdk=sdk,
                                             backend=backend,
                                             short_impl_name=short_impl_name,
                                             logger=app.logger.info,
                                             precompile_circuit=precompiled_circuit)

        except UnsupportedGateException as e:

            # unsupported gate type caused circuit conversion to fail
            app.logger.warn(f"Unsupported gate ({e.gate}) in implementation {short_impl_name}.")

            # precompile the circuit and retry
            if not precompiled_circuit:
                precompiled_circuit = True
                continue
            else:
                app.logger.warn(f"Precompiling {short_impl_name} failed.")
                break

        except TooManyQubitsException as e:
            # Too many qubits required for the provided backend
            app.logger.info(f"Transpile {short_impl_name} for {qpu_name}: too many qubits required")
            return jsonify({'error': 'too many qubits required'}), 200

        except Exception as e:
            app.logger.warn(f"Circuit compilation unexpectedly failed for {short_impl_name}.")
            abort(500)

    # After compilation the circuit should be valid
    if not backend.valid_circuit(circuit):
        app.logger.warn(f"Circuit compilation unexpectedly failed for {short_impl_name}.")
        abort(500)

    # get statistics about the compiled circuit
    width = circuit.n_qubits
    depth = circuit.depth()

    app.logger.info(f"Transpiled {short_impl_name} for {qpu_name}: w={width} d={depth}")
    return jsonify({'depth': depth, 'width': width}), 200


@app.route('/pytket-service/api/v1.0/execute', methods=['POST'])
def execute_circuit():
    """Put execution job in queue. Return location of the later result."""
    if not request.json or not 'impl-url' in request.json or not 'qpu-name' in request.json:
        abort(400)
    impl_url = request.json['impl-url']
    provider = request.json["provider"]
    sdk = request.json["sdk"]
    qpu_name = request.json['qpu-name']
    input_params = request.json.get('input-params', "")
    input_params = parameters.ParameterDictionary(input_params)
    shots = request.json.get('shots', 1024)

    job = app.execute_queue.enqueue('app.tasks.execute', impl_url=impl_url, qpu_name=qpu_name,
                                    input_params=input_params, shots=shots, provider= provider, sdk= sdk)
    result = Result(id=job.get_id())
    db.session.add(result)
    db.session.commit()

    logging.info('Returning HTTP response to client...')
    content_location = '/pytket-service/api/v1.0/results/' + result.id
    response = jsonify({'Location': content_location})
    response.status_code = 202
    response.headers['Location'] = content_location
    return response


@app.route('/pytket-service/api/v1.0/results/<result_id>', methods=['GET'])
def get_result(result_id):
    """Return result when it is available."""
    result = Result.query.get(result_id)
    if result.complete:
        result_dict = json.loads(result.result)
        return jsonify({'id': result.id, 'complete': result.complete, 'result': result_dict}), 200
    else:
        return jsonify({'id': result.id, 'complete': result.complete}), 200


@app.route('/pytket-service/api/v1.0/version', methods=['GET'])
def version():
    return jsonify({'version': '1.0'})
