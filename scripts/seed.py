"""Create demo identities and a reviewable release. Prints local credentials once."""
import json
import os
import urllib.request

base = os.getenv('API_URL', 'http://localhost:8080')
admin = os.environ['ADMIN_KEY']


def post(path, token, body):
    request = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                     headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


author = post('/admin/credentials', admin, {'tenant': 'demo', 'actor': 'alice', 'role': 'author'})
reviewer = post('/admin/credentials', admin, {'tenant': 'demo', 'actor': 'bob', 'role': 'reviewer'})
reader = post('/admin/credentials', admin, {'tenant': 'demo', 'actor': 'sdk', 'role': 'reader'})
post('/v1/environments', author['token'], {'name': 'prod'})
revision = post('/v1/environments/prod/revisions', author['token'], {'base_generation': 0,
                'bundle': {'flags': [{'key': 'new_checkout', 'rollout': 1000, 'salt': 'cohort-v1'}]}})
print('AUTHOR_TOKEN=' + author['token'])
print('REVIEWER_TOKEN=' + reviewer['token'])
print('SDK_TOKEN=' + reader['token'])
print('Draft ' + revision['id'] + ' awaits review. Open http://localhost:3000')
