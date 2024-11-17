import torch
from RealESRGAN import RealESRGAN
from PIL import Image

# Set file paths
model_path = 'RealESRGAN/weights/RealESRGAN_x4.pth'
input_image_path = 'lr_face.png'  # Replace with your actual input image name
output_image_path = 'output_image_1.png'

# Load the model
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model = RealESRGAN(device, scale=4)
model.load_weights(model_path)

# Load input image
input_image = Image.open(input_image_path).convert('RGB')

# Apply super-resolution
with torch.no_grad():
    output_image = model.predict(input_image)

# Save output image
output_image.save(output_image_path)
print(f"Output image saved at: {output_image_path}")

