import os
import uuid
import io
import shutil
import traceback
from flask import Flask, request, jsonify
from flask_cors import CORS
from PIL import Image
import torch
from RealESRGAN import RealESRGAN
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

import warnings
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=UserWarning)


app = Flask(__name__)
CORS(app)

# Constants
MAX_IMAGES = 100
MAX_UPSAMPLES = 3
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp'}

# Initialize the RealESRGAN model
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model = RealESRGAN(device, scale=4)
model.load_weights('weights/RealESRGAN_x4.pth', download=True)

def allowed_file(filename):
    """Check if the file has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/process_images', methods=['POST'])
def process_images():
    data = request.get_json()
    folder_id = data.get('folderId')
    access_token = data.get('accessToken')
    upsample_count = data.get('upsampleCount', 1)

    if not folder_id or not access_token:
        return jsonify({'error': 'Missing folderId or accessToken'}), 400

    if upsample_count > MAX_UPSAMPLES:
        return jsonify({'error': f'Maximum upsampling limit of {MAX_UPSAMPLES} reached.'}), 400

    # Authenticate with Google API using the access token
    try:
        credentials = Credentials(token=access_token)
        drive_service = build('drive', 'v3', credentials=credentials)
        app.logger.info('Authenticated with Google Drive API.')
    except Exception as e:
        app.logger.error(f'Authentication failed: {str(e)}')
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'Authentication with Google Drive API failed.'}), 500

    # Verify folder access
    try:
        folder = drive_service.files().get(fileId=folder_id, fields='id, name').execute()
        app.logger.info(f'Accessed folder: {folder.get("name")} (ID: {folder.get("id")})')
    except Exception as e:
        app.logger.error(f'Failed to access folder: {str(e)}')
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'Invalid folder ID or access denied.'}), 400

    # Get list of images in the folder
    try:
        query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed=false"
        results = drive_service.files().list(q=query, fields="files(id, name)", pageSize=MAX_IMAGES + 1).execute()
        files = results.get('files', [])
        total_images = len(files)
        app.logger.info(f'Found {total_images} images in the folder.')
    except Exception as e:
        app.logger.error(f'Error fetching files: {str(e)}')
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'Failed to retrieve files from the folder.'}), 500

    if total_images == 0:
        return jsonify({'error': 'No images found in the selected folder.'}), 400

    if total_images > MAX_IMAGES:
        return jsonify({'error': f'The selected folder contains more than {MAX_IMAGES} images.'}), 400

    # Create temporary directory
    temp_dir = f"temp_{uuid.uuid4()}"
    os.makedirs(temp_dir, exist_ok=True)
    app.logger.info(f'Created temporary directory: {temp_dir}')

    try:
        # Download images
        for file in files:
            file_id = file['id']
            file_name = file['name']
            try:
                app.logger.info(f'Downloading file: {file_name} (ID: {file_id})')
                request_dl = drive_service.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request_dl)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    if status:
                        app.logger.info(f'Download {int(status.progress() * 100)}% complete.')
                # Save to temporary directory
                with open(os.path.join(temp_dir, file_name), 'wb') as f:
                    f.write(fh.getvalue())
                fh.close()
                app.logger.info(f'Saved file to: {os.path.join(temp_dir, file_name)}')
            except Exception as e:
                app.logger.error(f'Error downloading file {file_name}: {str(e)}')
                app.logger.error(traceback.format_exc())
                return jsonify({'error': f'Failed to download file {file_name}.'}), 500

        # Create a parent folder in My Drive for all upsampled images
        try:
            parent_folder_metadata = {
                'name': 'Upsample',
                'mimeType': 'application/vnd.google-apps.folder'
                
            }
            parent_folder = drive_service.files().create(body=parent_folder_metadata, fields='id').execute()
            parent_folder_id = parent_folder.get('id')
            app.logger.info(f'Created parent folder "Upsample" with ID: {parent_folder_id}')
        except Exception as e:
            app.logger.error(f'Error creating parent folder: {str(e)}')
            app.logger.error(traceback.format_exc())
            return jsonify({'error': 'Failed to create parent folder in Google Drive.'}), 500

        # Initialize input directory
        input_dir = temp_dir

        # Process images and upload after each upsample iteration
        for i in range(upsample_count):
            app.logger.info(f'Starting upsample iteration {i + 1} of {upsample_count}')
            # Create a new output directory for this iteration
            output_dir = f"{temp_dir}_output_{i}"
            os.makedirs(output_dir, exist_ok=True)
            app.logger.info(f'Created output directory: {output_dir}')

            # Create a new folder in Drive for this upsample iteration
            try:
                folder_name = f'Upscaled_{i+1}x'
                folder_metadata = {
                    'name': folder_name,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [parent_folder_id]
                }
                folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
                new_folder_id = folder.get('id')
                app.logger.info(f'Created folder "{folder_name}" with ID: {new_folder_id}')
            except Exception as e:
                app.logger.error(f'Error creating upscaled folder: {str(e)}')
                app.logger.error(traceback.format_exc())
                return jsonify({'error': 'Failed to create upscaled folder in Google Drive.'}), 500

            # Process images
            for filename in os.listdir(input_dir):
                if not allowed_file(filename):
                    app.logger.warning(f'Skipping unsupported file type: {filename}')
                    continue
                input_path = os.path.join(input_dir, filename)
                output_path = os.path.join(output_dir, filename)
                try:
                    app.logger.info(f'Processing image: {filename}')
                    # Open and process image using 'with' to ensure closure
                    with Image.open(input_path) as image:
                        image = image.convert('RGB')
                        sr_image = model.predict(image)
                        sr_image.save(output_path)
                    app.logger.info(f'Saved upscaled image to: {output_path}')
                except Exception as e:
                    app.logger.error(f'Error processing image {filename}: {str(e)}')
                    app.logger.error(traceback.format_exc())
                    return jsonify({'error': f'Failed to process image {filename}.'}), 500

            # Upload images to Drive
            for filename in os.listdir(output_dir):
                file_metadata = {
                    'name': filename,
                    'parents': [new_folder_id]
                }
                file_path = os.path.join(output_dir, filename)
                try:
                    app.logger.info(f'Uploading image to Drive: {filename}')
                    media = MediaFileUpload(
                        file_path,
                        mimetype='image/jpeg',
                        resumable=True  # Ensure resumable is False
                    )
                    drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
                    app.logger.info(f'Uploaded image "{filename}" to folder ID: {new_folder_id}')
                    # Close the file descriptor if open
                    if media._fd:
                        media._fd.close()
                except Exception as e:
                    app.logger.error(f'Error uploading image {filename}: {str(e)}')
                    app.logger.error(traceback.format_exc())
                    return jsonify({'error': f'Failed to upload image {filename}.'}), 500

            # Set input_dir for next iteration
            input_dir = output_dir
            app.logger.info(f'Iteration {i + 1} completed. Preparing for next iteration.')

        return jsonify({'message': 'Images processed successfully'}), 200

    except Exception as e:
        app.logger.error(f'An unexpected error occurred: {str(e)}')
        app.logger.error(traceback.format_exc())
        return jsonify({'error': 'An internal error occurred.'}), 500
    finally:
        # Clean up temporary directories
        try:
            app.logger.info('Cleaning up temporary directories.')
            shutil.rmtree(temp_dir, ignore_errors=True)
            # Remove all output directories
            for i in range(upsample_count):
                output_dir = f"{temp_dir}_output_{i}"
                shutil.rmtree(output_dir, ignore_errors=True)
            app.logger.info('Cleanup completed.')
        except Exception as e:
            app.logger.error(f'Error cleaning up temporary directories: {e}')

if __name__ == '__main__':
    app.run(debug=True)


