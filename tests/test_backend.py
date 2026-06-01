import os
import sys
import unittest

# Adjust Python path to include the backend folder
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app import app

class TestBackendAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_ctx = TestClient(app)
        cls.client = cls.client_ctx.__enter__()
        
    @classmethod
    def tearDownClass(cls):
        cls.client_ctx.__exit__(None, None, None)
        
    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["backend"], "online")
        self.assertIn("camera", data)
        self.assertIn("model", data)
        
    def test_system_status_endpoint(self):
        response = self.client.get("/system/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("cpu_percent", data)
        self.assertIn("memory", data)
        self.assertIn("disk", data)
        self.assertIn("temperatures", data)
        
    def test_camera_status_endpoint(self):
        response = self.client.get("/camera/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("source", data)
        self.assertIn("width", data)
        self.assertIn("height", data)
        self.assertIn("is_mock", data)
        
    def test_model_status_endpoint(self):
        response = self.client.get("/model/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("model_name", data)
        self.assertIn("version", data)
        self.assertIn("loaded", data)
        
    def test_login_success(self):
        payload = {
            "username": "admin",
            "password": "admin123"
        }
        response = self.client.post("/auth/login", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["user"]["role"], "Admin")
        
    def test_login_failure(self):
        payload = {
            "username": "admin",
            "password": "wrongpassword"
        }
        response = self.client.post("/auth/login", json=payload)
        self.assertEqual(response.status_code, 401)

if __name__ == "__main__":
    unittest.main()
