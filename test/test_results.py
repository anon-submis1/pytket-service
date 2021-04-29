import unittest
import os
from app.config import basedir
from app import app, db
from app.result_model import Result


class ResultsTestCase(unittest.TestCase):

    def setUp(self):

        # setup environment variables for testing
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///" + os.path.join(basedir, 'test.db')

        self.client = app.test_client()
        db.create_all()

        self.create_dummy_results()

    @classmethod
    def create_dummy_results(cls):

        # Create incomplete dummy result
        r = Result(id="0")
        db.session.add(r)
        db.session.commit()

        # Create complete dummy result
        r = Result(id="1", complete=True, result="""
        {
            "text" : "I am complete !"
        }
        """)
        db.session.add(r)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()

    def test_version(self):

        response = self.client.get('/pytket-service/api/v1.0/version')

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertTrue("version" in json_data)
        self.assertEqual(json_data['version'], "1.0")

    def test_get_result_incomplete(self):

        result_id = "0"
        response = self.client.get('/pytket-service/api/v1.0/results/%s' % result_id)

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertTrue("complete" in result)
        self.assertEqual(result['complete'], False)

    def test_get_result_complete(self):

        result_id = "1"
        response = self.client.get('/pytket-service/api/v1.0/results/%s' % result_id)

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertTrue("complete" in result)
        self.assertTrue("result" in result)
        self.assertEqual(result['complete'], True)
        self.assertIn("complete", result["result"]['text'])


if __name__ == "__main__":
    unittest.main()