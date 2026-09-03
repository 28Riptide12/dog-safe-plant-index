"""Test suite for plant management API endpoints."""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone

# Add parent directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from app import app, init_plant_user_db, json_loads_strict, DuplicateKeyError


def test_json_loads_strict_rejects_duplicate_keys():
    """Duplicate object keys should fail instead of being silently overwritten."""
    with pytest.raises(DuplicateKeyError):
        json_loads_strict('{"name": "Rose", "name": "Lavender"}', 'duplicate.json')


@pytest.fixture
def client():
    """Create test client."""
    app.config['TESTING'] = True
    # Use a fresh database for testing
    init_plant_user_db()
    with app.test_client() as client:
        yield client


class TestPlantFavorites:
    """Test plant favorites API endpoints."""
    
    def test_get_empty_favorites(self, client):
        """Test getting favorites when none exist."""
        response = client.get('/api/plant-favorites?user_id=test_user')
        assert response.status_code == 200
        data = response.get_json()
        assert data['user_id'] == 'test_user'
        assert data['favorites'] == []
    
    def test_add_favorite(self, client):
        """Test adding a plant to favorites."""
        response = client.post('/api/plant-favorites',
            json={'user_id': 'test_user', 'plant_id': 'rose'}
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data['plant_id'] == 'rose'
        assert data['user_id'] == 'test_user'
        assert 'id' in data
        assert 'added_date' in data
    
    def test_add_duplicate_favorite(self, client):
        """Test adding the same plant twice fails."""
        client.post('/api/plant-favorites',
            json={'user_id': 'test_user', 'plant_id': 'rose'}
        )
        response = client.post('/api/plant-favorites',
            json={'user_id': 'test_user', 'plant_id': 'rose'}
        )
        assert response.status_code == 409
        assert 'already in your favorites' in response.get_json()['error']
    
    def test_get_favorites(self, client):
        """Test retrieving favorites."""
        client.post('/api/plant-favorites',
            json={'user_id': 'test_user', 'plant_id': 'rose'}
        )
        client.post('/api/plant-favorites',
            json={'user_id': 'test_user', 'plant_id': 'tulip'}
        )
        response = client.get('/api/plant-favorites?user_id=test_user')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data['favorites']) == 2
        plant_ids = {fav['plant_id'] for fav in data['favorites']}
        assert plant_ids == {'rose', 'tulip'}
    
    def test_delete_favorite(self, client):
        """Test removing a favorite."""
        client.post('/api/plant-favorites',
            json={'user_id': 'test_user', 'plant_id': 'rose'}
        )
        response = client.delete('/api/plant-favorites/rose?user_id=test_user')
        assert response.status_code == 200
        
        # Verify it's gone
        response = client.get('/api/plant-favorites?user_id=test_user')
        assert len(response.get_json()['favorites']) == 0
    
    def test_delete_nonexistent_favorite(self, client):
        """Test deleting a non-existent favorite."""
        response = client.delete('/api/plant-favorites/rose?user_id=test_user')
        assert response.status_code == 404


class TestUserPlants:
    """Test plant library API endpoints."""
    
    def test_get_empty_library(self, client):
        """Test getting plants when none exist."""
        response = client.get('/api/user-plants?user_id=test_user')
        assert response.status_code == 200
        data = response.get_json()
        assert data['user_id'] == 'test_user'
        assert data['plants'] == []
    
    def test_add_plant_to_library(self, client):
        """Test adding a plant to the library."""
        response = client.post('/api/user-plants',
            json={
                'user_id': 'test_user',
                'plant_id': 'rose',
                'plant_name': 'Red Rose',
                'location_name': 'Front garden',
                'plant_notes': 'Beautiful red roses'
            }
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data['plant_id'] == 'rose'
        assert data['plant_name'] == 'Red Rose'
        assert data['location_name'] == 'Front garden'
        assert data['health_status'] == 'good'
        assert 'id' in data
    
    def test_get_plants_in_library(self, client):
        """Test retrieving plants from library."""
        client.post('/api/user-plants',
            json={
                'user_id': 'test_user',
                'plant_id': 'rose',
                'plant_name': 'Red Rose',
                'location_name': 'Front garden'
            }
        )
        response = client.get('/api/user-plants?user_id=test_user')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data['plants']) == 1
        assert data['plants'][0]['plant_id'] == 'rose'
    
    def test_update_plant(self, client):
        """Test updating a plant in library."""
        add_response = client.post('/api/user-plants',
            json={
                'user_id': 'test_user',
                'plant_id': 'rose',
                'plant_name': 'Red Rose',
                'location_name': 'Front garden'
            }
        )
        plant_id = add_response.get_json()['id']
        
        response = client.put(f'/api/user-plants/{plant_id}',
            json={
                'user_id': 'test_user',
                'location_name': 'Back garden',
                'health_status': 'excellent'
            }
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['location_name'] == 'Back garden'
        assert data['health_status'] == 'excellent'
    
    def test_delete_plant(self, client):
        """Test removing a plant from library."""
        add_response = client.post('/api/user-plants',
            json={
                'user_id': 'test_user',
                'plant_id': 'rose',
                'plant_name': 'Red Rose',
                'location_name': 'Front garden'
            }
        )
        plant_id = add_response.get_json()['id']
        
        response = client.delete(f'/api/user-plants/{plant_id}?user_id=test_user')
        assert response.status_code == 200
        
        # Verify it's gone
        response = client.get('/api/user-plants?user_id=test_user')
        assert len(response.get_json()['plants']) == 0


class TestCareTasks:
    """Test care tasks API endpoints."""
    
    def setup_method(self):
        """Setup test data before each test."""
        self.client = app.test_client()
        init_plant_user_db()
    
    def test_get_empty_tasks(self):
        """Test getting tasks when none exist."""
        response = self.client.get('/api/care-tasks?user_id=test_user')
        assert response.status_code == 200
        data = response.get_json()
        assert data['user_id'] == 'test_user'
        assert data['tasks'] == []
    
    def test_create_care_task(self):
        """Test creating a care task."""
        # First add a plant
        plant_response = self.client.post('/api/user-plants',
            json={
                'user_id': 'test_user',
                'plant_id': 'rose',
                'plant_name': 'Red Rose',
                'location_name': 'Front garden'
            }
        )
        plant_id = plant_response.get_json()['id']
        
        # Create task
        response = self.client.post('/api/care-tasks',
            json={
                'user_plant_id': plant_id,
                'task_type': 'water',
                'frequency_days': 3
            }
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data['task_type'] == 'water'
        assert data['frequency_days'] == 3
        assert data['status'] == 'pending'
        assert 'next_due_date' in data
    
    def test_invalid_task_type(self):
        """Test creating a task with invalid type."""
        plant_response = self.client.post('/api/user-plants',
            json={
                'user_id': 'test_user',
                'plant_id': 'rose',
                'plant_name': 'Red Rose',
                'location_name': 'Front garden'
            }
        )
        plant_id = plant_response.get_json()['id']
        
        response = self.client.post('/api/care-tasks',
            json={
                'user_plant_id': plant_id,
                'task_type': 'invalid_type',
                'frequency_days': 3
            }
        )
        assert response.status_code == 400
        assert 'Invalid task_type' in response.get_json()['error']
    
    def test_get_tasks(self):
        """Test retrieving care tasks."""
        # Add plant and tasks
        plant_response = self.client.post('/api/user-plants',
            json={
                'user_id': 'test_user',
                'plant_id': 'rose',
                'plant_name': 'Red Rose',
                'location_name': 'Front garden'
            }
        )
        plant_id = plant_response.get_json()['id']
        
        self.client.post('/api/care-tasks',
            json={'user_plant_id': plant_id, 'task_type': 'water', 'frequency_days': 3}
        )
        self.client.post('/api/care-tasks',
            json={'user_plant_id': plant_id, 'task_type': 'feed', 'frequency_days': 14}
        )
        
        response = self.client.get('/api/care-tasks?user_id=test_user')
        assert response.status_code == 200
        data = response.get_json()
        assert len(data['tasks']) == 2
        task_types = {task['task_type'] for task in data['tasks']}
        assert task_types == {'water', 'feed'}
    
    def test_complete_task(self):
        """Test completing a care task."""
        # Setup
        plant_response = self.client.post('/api/user-plants',
            json={
                'user_id': 'test_user',
                'plant_id': 'rose',
                'plant_name': 'Red Rose',
                'location_name': 'Front garden'
            }
        )
        plant_id = plant_response.get_json()['id']
        
        task_response = self.client.post('/api/care-tasks',
            json={'user_plant_id': plant_id, 'task_type': 'water', 'frequency_days': 3}
        )
        task_id = task_response.get_json()['id']
        
        # Complete task
        response = self.client.put(f'/api/care-tasks/{task_id}/complete')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'completed'
        assert data['last_done_date'] is not None
        assert data['next_due_date'] is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
