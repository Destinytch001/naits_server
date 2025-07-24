from flask import Blueprint, request, jsonify, current_app
from bson import ObjectId
from werkzeug.exceptions import BadRequest, NotFound
import datetime
import cloudinary
import cloudinary.uploader
import cloudinary.api
import os
print("✅ faculty wear module initialized")
faculty_wear_bp = Blueprint('faculty_wear', __name__, url_prefix='/api/faculty-wear')
collection = None

def upload_to_cloudinary(file):
    try:
        # Validate file type and size before upload
        if not file.content_type.startswith('image/'):
            raise BadRequest("Only image files are allowed")
        
        # Check file size (limit to 10MB)
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        if file_size > 10 * 1024 * 1024:  # 10MB
            raise BadRequest("Image size must be less than 10MB")

        upload_result = cloudinary.uploader.upload(
            file,
            folder="faculty_wear",
            resource_type="image",
            quality="auto",
            fetch_format="auto"
        )
        return upload_result.get('secure_url')
    except BadRequest as e:
        raise e
    except Exception as e:
        current_app.logger.error(f"Cloudinary upload failed: {str(e)}")
        raise BadRequest("Failed to upload image to Cloudinary")

def delete_from_cloudinary(image_url):
    try:
        if not image_url or 'cloudinary.com' not in image_url:
            return False
            
        # Extract public_id from URL
        parts = image_url.split('/')
        folder = parts[-2] if parts[-2] != 'upload' else None
        public_id = parts[-1].split('.')[0]
        
        if folder:
            public_id = f"{folder}/{public_id}"
            
        result = cloudinary.uploader.destroy(public_id)
        return result.get('result') == 'ok'
    except Exception as e:
        current_app.logger.error(f"Cloudinary delete failed: {str(e)}")
        return False

@faculty_wear_bp.route('/', methods=['GET'])
def get_all_wear():
    try:
        items = list(collection.find().sort("created_at", -1))
        for item in items:
            item['_id'] = str(item['_id'])
            item['standard_price'] = float(item['standard_price'])
            item['custom_price'] = float(item['custom_price'])
        return jsonify({"status": "success", "data": items}), 200
    except Exception as e:
        current_app.logger.error(f"Error fetching products: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to fetch products"}), 500

@faculty_wear_bp.route('/<item_id>', methods=['GET'])
def get_wear(item_id):
    try:
        if not ObjectId.is_valid(item_id):
            raise BadRequest("Invalid product ID format")
            
        item = collection.find_one({'_id': ObjectId(item_id)})
        if not item:
            raise NotFound("Product not found")
        
        item['_id'] = str(item['_id'])
        item['standard_price'] = float(item['standard_price'])
        item['custom_price'] = float(item['custom_price'])
        return jsonify({"status": "success", "data": item}), 200
    except NotFound as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except BadRequest as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error fetching product {item_id}: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to fetch product"}), 500

@faculty_wear_bp.route('/', methods=['POST'])
def add_wear():
    try:
        # Initialize variables
        image_url = None
        file = None
        
        # Check if request is multipart form-data
        if request.content_type.startswith('multipart/form-data'):
            if 'image_upload' in request.files:
                file = request.files['image_upload']
                if file.filename != '':
                    image_url = upload_to_cloudinary(file)
            image_url = image_url or request.form.get('image_url', '')
            data = request.form
        else:
            # Handle JSON request
            data = request.get_json()
            image_url = data.get('image_url', '')
        
        # Validate required fields
        required_fields = ['title', 'description', 'standard_price',
                         'custom_price', 'add_to_cart_text', 'buy_now_text']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            raise BadRequest(f"Missing required fields: {', '.join(missing_fields)}")
        
        # Validate prices
        try:
            standard_price = float(data['standard_price'])
            custom_price = float(data['custom_price'])
            if standard_price < 0 or custom_price < 0:
                raise ValueError("Prices cannot be negative")
        except ValueError:
            raise BadRequest("Invalid price format")

        # Create product document
        wear = {
            "title": data['title'].strip(),
            "description": data['description'].strip(),
            "image_url": image_url,
            "badge_text": data.get('badge_text', '').strip(),
            "standard_price": standard_price,
            "custom_price": custom_price,
            "add_to_cart_text": data['add_to_cart_text'].strip(),
            "add_to_cart_link": data.get('add_to_cart_link', '#').strip(),
            "buy_now_text": data['buy_now_text'].strip(),
            "buy_now_link": data.get('buy_now_link', '#').strip(),
            "created_at": datetime.datetime.utcnow(),
            "updated_at": datetime.datetime.utcnow()
        }

        # Insert into database
        result = collection.insert_one(wear)
        wear['_id'] = str(result.inserted_id)
        
        return jsonify({
            "status": "success", 
            "message": "Product created successfully",
            "data": wear
        }), 201

    except BadRequest as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error creating product: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to create product"}), 500

@faculty_wear_bp.route('/<item_id>', methods=['PUT'])
def update_wear(item_id):
    try:
        if not ObjectId.is_valid(item_id):
            raise BadRequest("Invalid product ID format")
            
        # Get existing product
        existing_item = collection.find_one({'_id': ObjectId(item_id)})
        if not existing_item:
            raise NotFound("Product not found")

        # Initialize variables
        image_url = existing_item.get('image_url', '')
        file = None
        data = {}
        
        # Check content type
        if request.content_type.startswith('multipart/form-data'):
            if 'image_upload' in request.files:
                file = request.files['image_upload']
                if file.filename != '':
                    # Delete old image if exists
                    if existing_item.get('image_url'):
                        delete_from_cloudinary(existing_item['image_url'])
                    # Upload new image
                    image_url = upload_to_cloudinary(file)
            image_url = image_url or request.form.get('image_url', '')
            data = request.form
        else:
            # Handle JSON request
            data = request.get_json()
            if 'image_url' in data:
                # Delete old image if it was from Cloudinary
                if existing_item.get('image_url') and 'cloudinary.com' in existing_item['image_url']:
                    delete_from_cloudinary(existing_item['image_url'])
                image_url = data.get('image_url', '')
        
        # Validate required fields
        required_fields = ['title', 'description', 'standard_price',
                         'custom_price', 'add_to_cart_text', 'buy_now_text']
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            raise BadRequest(f"Missing required fields: {', '.join(missing_fields)}")
        
        # Validate prices
        try:
            standard_price = float(data['standard_price'])
            custom_price = float(data['custom_price'])
            if standard_price < 0 or custom_price < 0:
                raise ValueError("Prices cannot be negative")
        except ValueError:
            raise BadRequest("Invalid price format")

        # Prepare updates
        updates = {
            "$set": {
                "title": data['title'].strip(),
                "description": data['description'].strip(),
                "image_url": image_url,
                "badge_text": data.get('badge_text', '').strip(),
                "standard_price": standard_price,
                "custom_price": custom_price,
                "add_to_cart_text": data['add_to_cart_text'].strip(),
                "add_to_cart_link": data.get('add_to_cart_link', '#').strip(),
                "buy_now_text": data['buy_now_text'].strip(),
                "buy_now_link": data.get('buy_now_link', '#').strip(),
                "updated_at": datetime.datetime.utcnow()
            }
        }

        # Update database
        result = collection.update_one(
            {'_id': ObjectId(item_id)},
            updates
        )

        if result.matched_count == 0:
            raise NotFound("Product not found")
        
        # Return updated product
        item = collection.find_one({'_id': ObjectId(item_id)})
        item['_id'] = str(item['_id'])
        item['standard_price'] = float(item['standard_price'])
        item['custom_price'] = float(item['custom_price'])
        
        return jsonify({
            "status": "success", 
            "message": "Product updated successfully",
            "data": item
        }), 200

    except BadRequest as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except NotFound as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except Exception as e:
        current_app.logger.error(f"Error updating product {item_id}: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to update product"}), 500

@faculty_wear_bp.route('/<item_id>', methods=['DELETE'])
def delete_wear(item_id):
    try:
        if not ObjectId.is_valid(item_id):
            raise BadRequest("Invalid product ID format")
            
        item = collection.find_one({'_id': ObjectId(item_id)})
        if not item:
            raise NotFound("Product not found")
            
        # Delete image from Cloudinary if it exists
        if item.get('image_url') and 'cloudinary.com' in item['image_url']:
            delete_from_cloudinary(item['image_url'])
        
        # Delete from database
        result = collection.delete_one({'_id': ObjectId(item_id)})
        if result.deleted_count == 0:
            raise NotFound("Product not found")
            
        return jsonify({
            "status": "success", 
            "message": "Product deleted successfully"
        }), 200
        
    except NotFound as e:
        return jsonify({"status": "error", "message": str(e)}), 404
    except BadRequest as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"Error deleting product {item_id}: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to delete product"}), 500

def init_faculty_wear_routes(app, db):
    global collection
    collection = db['faculty_wear']
    
    # Hardcoded Cloudinary configuration
    cloudinary.config(
        cloud_name="dhndd1msa",
        api_key="337382597786761",
        api_secret="bEJ0sWFZi8yYzeP5lzVl_rmUtX8",
        secure=True
    )
    
    # Verify Cloudinary connection
    try:
        result = cloudinary.api.ping()
        if not result.get('status') == 'ok':
            app.logger.error("Cloudinary ping failed")
            raise RuntimeError("Failed to verify Cloudinary connection")
        app.logger.info("Cloudinary connection successful")
    except Exception as e:
        app.logger.error(f"Cloudinary connection failed: {str(e)}")
        raise RuntimeError("Failed to connect to Cloudinary")
    
    app.register_blueprint(faculty_wear_bp)

