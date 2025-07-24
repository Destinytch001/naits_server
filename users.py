from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone
from flask_jwt_extended import decode_token
import jwt
import os
import re

# Blueprint setup
users_bp = Blueprint('users', __name__)

# Globals to be set by init_users_routes
users_collection = None
get_wat_time = None
STATUS_CONFIG = None
SECRET_KEY = os.getenv('JWT_SECRET', 'dev-secret')  # Override in production


# ========== Initializer ==========
def init_users_routes(app, db, wat_time_func, status_config):
    global users_collection, get_wat_time, STATUS_CONFIG
    users_collection = db.users
    get_wat_time = wat_time_func
    STATUS_CONFIG = status_config
    app.register_blueprint(users_bp)

from functools import wraps
from flask import request, jsonify

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if not token:
            return jsonify({'success': False, 'error': 'Token missing'}), 401
        try:
            decoded = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            request.user_id = decoded['user_id']
            return f(*args, **kwargs)
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'error': 'Invalid token'}), 401
    return decorated




# ========== Helpers ==========
def sanitize_user_data(user):
    return {
        'id': str(user['_id']),
        'first_name': user['first_name'],
        'last_name': user['last_name'],
        'nickname': user['nickname'],
        'department': user['department'],
        'level': user['level'],
        'email': user.get('email', ''),
        'whatsapp': user.get('whatsapp', ''),
        'last_login': user.get('last_login'),
        'status': user.get('status', 'active'),
        'updated_at': user.get('updated_at')
    }


def validate_signup_data(data):
    errors = []
    required_fields = {
        'first_name': 'First name is required',
        'last_name': 'Last name is required',
        'birthday': 'Birthday is required (MM-DD format)',
        'nickname': 'Nickname is required',
        'department': 'Department is required',
        'level': 'Level is required',
        'whatsapp': 'WhatsApp number is required (11 digits)',
        'password': 'Password is required (min 10 characters)'
    }

    for field, message in required_fields.items():
        if not data.get(field):
            errors.append(message)

    if data.get('birthday') and not re.match(r'^\d{2}-\d{2}$', data['birthday']):
        errors.append('Birthday must be in MM-DD format')

    if data.get('whatsapp') and not re.match(r'^\d{11}$', data['whatsapp']):
        errors.append('WhatsApp number must be 11 digits')

    if data.get('password') and len(data['password']) < 10:
        errors.append('Password must be at least 10 characters')

    return errors

def user_exists(nickname, whatsapp):
    return users_collection.find_one({
        '$or': [
            {'nickname': nickname.lower()},
            {'whatsapp': whatsapp}
        ]
    })

def create_user(data):
    now = get_wat_time()
    user = {
        'first_name': data['first_name'].strip(),
        'last_name': data['last_name'].strip(),
        'birthday': data['birthday'],
        'nickname': data['nickname'].strip().lower(),
        'department': data['department'].upper(),
        'level': data['level'].upper(),
        'whatsapp': data['whatsapp'],
        'email': data.get('email', '').strip().lower(),
        'password': generate_password_hash(data['password']),
        'created_at': now,
        'updated_at': now,
        'last_login': None,
        'status': 'active',
        'last_seen': None,
        'last_notification_check': datetime.min.replace(tzinfo=timezone.utc)
    }
    result = users_collection.insert_one(user)
    return result.inserted_id


# ========== Routes ==========

# --- Signup ---
@users_bp.route('/api/auth/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400

        errors = validate_signup_data(data)
        if errors:
            return jsonify({'success': False, 'error': 'Validation failed', 'details': errors}), 400

        if user_exists(data['nickname'], data['whatsapp']):
            return jsonify({'success': False, 'error': 'User already exists'}), 400

        user_id = create_user(data)
        user = users_collection.find_one({'_id': user_id})

        return jsonify({
            'success': True,
            'user': sanitize_user_data(user),
            'message': 'Registration successful'
        }), 201

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# --- Signin ---
@users_bp.route('/api/auth/signin', methods=['POST'])
def signin():
    try:
        data = request.get_json()
        if not data or 'nickname' not in data or 'password' not in data:
            return jsonify({'success': False, 'error': 'Nickname and password are required'}), 400

        user = users_collection.find_one({
            'nickname': {'$regex': f'^{data["nickname"]}$', '$options': 'i'}
        })

        if not user or not check_password_hash(user.get('password', ''), data['password']):
            return jsonify({'success': False, 'error': 'Invalid credentials'}), 401

        token_payload = {
            'user_id': str(user['_id']),
            'nickname': user['nickname'],
            'exp': datetime.utcnow() + timedelta(hours=2)
        }

        token = jwt.encode(token_payload, SECRET_KEY, algorithm='HS256')

        users_collection.update_one(
            {'_id': user['_id']},
            {'$set': {'last_login': get_wat_time()}}
        )

        return jsonify({
            'success': True,
            'token': token,
            'user': sanitize_user_data(user)
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# --- Get All Users (Admin Only) ---
@users_bp.route('/api/users', methods=['GET'])
def get_users():
    try:
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 10))
        search = request.args.get('search', '')
        department = request.args.get('department', '')
        level = request.args.get('level', '')
        status = request.args.get('status', '')

        query = {}
        if search:
            query['$or'] = [
                {'first_name': {'$regex': search, '$options': 'i'}},
                {'last_name': {'$regex': search, '$options': 'i'}},
                {'nickname': {'$regex': search, '$options': 'i'}},
                {'email': {'$regex': search, '$options': 'i'}}
            ]
        if department:
            query['department'] = department
        if level:
            query['level'] = level
        if status:
            query['status'] = status.lower()

        total = users_collection.count_documents(query)
        skip = (page - 1) * per_page
        users = list(users_collection.find(query).skip(skip).limit(per_page))

        return jsonify({
            'success': True,
            'users': [sanitize_user_data(user) for user in users],
            'total': total,
            'page': page,
            'per_page': per_page
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# --- Heartbeat (User must be authenticated) ---
@users_bp.route('/api/auth/heartbeat', methods=['POST'])
@requires_auth
def user_heartbeat():
    try:
        users_collection.update_one(
            {'_id': ObjectId(request.user_id)},
            {
                '$set': {
                    'status': 'online',
                    'last_active': get_wat_time(),
                    'last_seen': get_wat_time()
                }
            }
        )
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# --- Background Task ---
def check_user_status():
    try:
        now = get_wat_time()

        idle_threshold = now - timedelta(minutes=STATUS_CONFIG['IDLE_THRESHOLD'])
        offline_threshold = now - timedelta(minutes=STATUS_CONFIG['OFFLINE_THRESHOLD'])

        users_collection.update_many(
            {
                'status': 'online',
                'last_active': {'$lt': idle_threshold}
            },
            {'$set': {'status': 'idle'}}
        )

        users_collection.update_many(
            {
                '$or': [{'status': 'online'}, {'status': 'idle'}],
                'last_active': {'$lt': offline_threshold}
            },
            {'$set': {'status': 'offline'}}
        )
    except Exception as e:
        print(f"Status check failed: {str(e)}")


# --- Get User Status ---
@users_bp.route('/api/users/status/<user_id>', methods=['GET'])
@requires_auth
def get_user_status(user_id):
    try:
        user = users_collection.find_one(
            {'_id': ObjectId(user_id)},
            {'status': 1, 'last_active': 1, 'first_name': 1, 'department': 1}
        )

        if not user:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        status = user.get('status', 'offline')
        last_active = user.get('last_active')

        if last_active:
            inactive_for = (get_wat_time() - last_active).total_seconds() / 60

            if inactive_for > STATUS_CONFIG['OFFLINE_THRESHOLD']:
                status = 'offline'
            elif inactive_for > STATUS_CONFIG['IDLE_THRESHOLD']:
                status = 'idle'

            if status != user.get('status'):
                users_collection.update_one(
                    {'_id': ObjectId(user_id)},
                    {'$set': {'status': status}}
                )

        return jsonify({
            'success': True,
            'status': status,
            'last_seen': last_active.isoformat() if last_active else None,
            'first_name': user.get('first_name'),
            'department': user.get('department'),
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@users_bp.route('/api/users/<user_id>', methods=['DELETE'])
def delete_user(user_id):
    try:
        if not ObjectId.is_valid(user_id):
            return jsonify({'success': False, 'error': 'Invalid user ID'}), 400

        result = users_collection.delete_one({'_id': ObjectId(user_id)})

        if result.deleted_count == 0:
            return jsonify({'success': False, 'error': 'User not found'}), 404

        return jsonify({'success': True, 'message': 'User deleted successfully'})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
@users_bp.route('/api/users/bulk-create', methods=['POST'])
def bulk_create_users():
    try:
        data = request.get_json()

        if not data or not isinstance(data, list):
            return jsonify({'success': False, 'error': 'Invalid data: Expected a list of user objects'}), 400

        created = []
        skipped = []

        for index, user_data in enumerate(data, start=1):
            errors = validate_signup_data(user_data)
            if errors:
                skipped.append({
                    'index': index,
                    'nickname': user_data.get('nickname', ''),
                    'errors': errors
                })
                continue

            if user_exists(user_data['nickname'], user_data['whatsapp']):
                skipped.append({
                    'index': index,
                    'nickname': user_data['nickname'],
                    'errors': ['User already exists']
                })
                continue

            user_id = create_user(user_data)
            created.append(str(user_id))

        return jsonify({
            'success': True,
            'created_count': len(created),
            'skipped_count': len(skipped),
            'created_user_ids': created,
            'skipped': skipped
        }), 201

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

print("✅ Users module initialized")