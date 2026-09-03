import json
import sys
import requests

BASE = 'http://127.0.0.1:5000'

def show(resp):
    print(resp.status_code, resp.reason)
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text[:1000])

try:
    print('GET /plants')
    show(requests.get(BASE + '/plants'))

    print('GET /api/dog-safe-plants')
    show(requests.get(BASE + '/api/dog-safe-plants'))

    print('GET /api/plant-favorites')
    show(requests.get(BASE + '/api/plant-favorites?user_id=smoke'))

    print('GET /api/health/paths')
    show(requests.get(BASE + '/api/health/paths'))

    print('GET /api/plant-review-queue')
    show(requests.get(BASE + '/api/plant-review-queue'))

    print('\nPlant smoke tests completed successfully')
except Exception as error:
    print('Plant smoke test failed:', error)
    sys.exit(2)
