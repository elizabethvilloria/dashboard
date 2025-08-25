#!/usr/bin/env python3
"""
Test script to verify the selection flow works correctly
"""

from flask import Flask, session
from dashboard import app

# Test the selection flow
def test_selection_flow():
    with app.test_client() as client:
        # Test 1: Login first
        print("Testing login...")
        response = client.post('/login', data={
            'username': 'admin',
            'password': '1010'
        }, follow_redirects=True)
        print(f"Login response status: {response.status_code}")
        
        # Test 2: Try to access dashboard without selection
        print("\nTesting dashboard access without selection...")
        response = client.get('/')
        print(f"Dashboard response status: {response.status_code}")
        print(f"Redirected to: {response.location}")
        
        # Test 3: Access selection page
        print("\nTesting selection page access...")
        response = client.get('/selection')
        print(f"Selection page response status: {response.status_code}")
        
        # Test 4: Submit selection
        print("\nTesting selection submission...")
        response = client.post('/process-selection', data={
            'city': 'manila',
            'toda': 'bltmpc',
            'etrike': '00001'
        }, follow_redirects=True)
        print(f"Selection submission response status: {response.status_code}")
        
        # Test 5: Try to access dashboard after selection
        print("\nTesting dashboard access after selection...")
        response = client.get('/')
        print(f"Dashboard response status: {response.status_code}")
        
        # Test 6: Try to access selection page after completion
        print("\nTesting selection page access after completion...")
        response = client.get('/selection')
        print(f"Selection page response status: {response.status_code}")
        print(f"Redirected to: {response.location}")
        
        print("\n✅ Selection flow test completed!")

if __name__ == '__main__':
    test_selection_flow()
