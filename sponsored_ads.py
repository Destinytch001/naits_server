from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from pymongo import MongoClient
from bson import ObjectId
import os
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
import cloudinary.api
print("✅ Sponsored ads module initialized")
# Load environment variables
load_dotenv()

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

# Create Blueprint
sponsored_ads_bp = Blueprint('sponsored_ads', __name__)

# MongoDB setup
client = MongoClient(os.environ.get("MONGO_URI"))
db = client.get_database()
ads_collection = db.sponsored_ads

def get_wat_time():
    """Get current time in WAT (UTC+1)"""
    return datetime.utcnow() + timedelta(hours=1)

@sponsored_ads_bp.route('/api/admin/sponsored-ads', methods=['POST'])
def create_sponsored_ad():
    try:
        # Get form data
        title = request.form.get('title')
        description = request.form.get('description')
        sponsor_name = request.form.get('sponsor_name')
        whatsapp_number = request.form.get('whatsapp_number')
        duration_days = int(request.form.get('duration_days', 7))  # Default 7 days
        sponsor_logo = request.files.get('sponsor_logo')
        ad_image = request.files.get('ad_image')

        # Validate required fields
        if not all([title, description, sponsor_name, whatsapp_number]):
            return jsonify({'success': False, 'error': 'Missing required fields'}), 400

        # Upload images to Cloudinary
        upload_results = {}
        if sponsor_logo:
            logo_upload = cloudinary.uploader.upload(sponsor_logo, folder="sponsored_ads/logos")
            upload_results['sponsor_logo_url'] = logo_upload['secure_url']
            upload_results['sponsor_logo_public_id'] = logo_upload['public_id']

        if ad_image:
            image_upload = cloudinary.uploader.upload(ad_image, folder="sponsored_ads/images")
            upload_results['ad_image_url'] = image_upload['secure_url']
            upload_results['ad_image_public_id'] = image_upload['public_id']

        # Calculate expiration time
        created_at = get_wat_time()
        expires_at = created_at + timedelta(days=duration_days)

        # Create ad document
        ad_data = {
            'title': title,
            'description': description,
            'sponsor_name': sponsor_name,
            'whatsapp_number': whatsapp_number,
            'created_at': created_at,
            'expires_at': expires_at,
            'is_active': True,
            **upload_results
        }

        # Insert into database
        result = ads_collection.insert_one(ad_data)
        ad_id = str(result.inserted_id)

        return jsonify({
            'success': True,
            'message': 'Sponsored ad created successfully',
            'ad_id': ad_id
        }), 201

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@sponsored_ads_bp.route('/api/sponsored-ads', methods=['GET'])
def get_active_ads():
    try:
        current_time = get_wat_time()
        
        # Find active ads that haven't expired
        active_ads = list(ads_collection.find({
            'is_active': True,
            'expires_at': {'$gt': current_time}
        }).sort('created_at', -1))

        # Convert ObjectId to string and format response
        ads_list = []
        for ad in active_ads:
            ad['_id'] = str(ad['_id'])
            ads_list.append(ad)

        return jsonify({
            'success': True,
            'ads': ads_list
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@sponsored_ads_bp.route('/api/admin/sponsored-ads/<ad_id>', methods=['DELETE'])
def delete_ad(ad_id):
    try:
        # First try to delete images from Cloudinary
        ad = ads_collection.find_one({'_id': ObjectId(ad_id)})
        if not ad:
            return jsonify({'success': False, 'error': 'Ad not found'}), 404

        # Delete images from Cloudinary if they exist
        if 'sponsor_logo_public_id' in ad:
            cloudinary.uploader.destroy(ad['sponsor_logo_public_id'])
        if 'ad_image_public_id' in ad:
            cloudinary.uploader.destroy(ad['ad_image_public_id'])

        # Delete from database
        ads_collection.delete_one({'_id': ObjectId(ad_id)})

        return jsonify({
            'success': True,
            'message': 'Ad deleted successfully'
        }), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

def check_expired_ads():
    """Background task to deactivate expired ads"""
    try:
        current_time = get_wat_time()
        
        # Find and deactivate expired ads
        result = ads_collection.update_many(
            {
                'expires_at': {'$lte': current_time},
                'is_active': True
            },
            {'$set': {'is_active': False}}
        )
        
        if result.modified_count > 0:
            print(f"Deactivated {result.modified_count} expired ads")
            
    except Exception as e:
        print(f"Error in ad expiration check: {str(e)}")

def init_sponsored_ads_module(app):
    """Initialize the sponsored ads module"""
    # Register blueprint
    app.register_blueprint(sponsored_ads_bp, url_prefix='/')
    
    # Create index for expiration
    ads_collection.create_index([("expires_at", 1)])
    ads_collection.create_index([("is_active", 1)])
    
@sponsored_ads_bp.route('/api/admin/sponsored-ads/expired', methods=['GET'])
def get_expired_ads():
    try:
        current_time = get_wat_time()
        expired_ads = list(ads_collection.find({
            'expires_at': {'$lte': current_time}
        }).sort('created_at', -1))

        for ad in expired_ads:
            ad['_id'] = str(ad['_id'])

        return jsonify({
            'success': True,
            'ads': expired_ads
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
@sponsored_ads_bp.route('/api/admin/sponsored-ads/<ad_id>/extend', methods=['POST'])
def extend_ad(ad_id):
    try:
        ad = ads_collection.find_one({'_id': ObjectId(ad_id)})
        if not ad:
            return jsonify({'success': False, 'error': 'Ad not found'}), 404

        new_expires_at = ad['expires_at'] + timedelta(days=7)
        ads_collection.update_one(
            {'_id': ObjectId(ad_id)},
            {'$set': {
                'expires_at': new_expires_at,
                'is_active': True
            }}
        )

        return jsonify({
            'success': True,
            'message': 'Ad extended successfully'
        }), 200
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
