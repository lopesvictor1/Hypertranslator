import os
import random
import deepl
import requests
from googleapiclient.discovery import build
from flask import Flask, render_template, request, Response
from dotenv import load_dotenv
import json
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import base64
import textwrap

# Load environment variables from .env file
load_dotenv()

# Get API keys from environment variables
DEEPL_AUTH_KEY = os.getenv("DEEPL_AUTH_KEY")
GOOGLE_API_KEY = os.getenv("CUSTOM_SEARCH_API_KEY")
GOOGLE_CX = os.getenv("GOOGLE_CX")

# Initialize DeepL Translator
translator = deepl.Translator(DEEPL_AUTH_KEY)

# Initialize Flask app
app = Flask(__name__)

# Function to get the first image from Google search
def get_image_url(query):
    service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
    res = service.cse().list(q=query, cx=GOOGLE_CX, searchType="image").execute()
    try:
        # Return the URL of the first image
        return res["items"][0]["link"]
    except KeyError:
        return None

# Function to add text to an image
def add_text_to_image(image_url, text, font_size_factor=20):
    try:
        # Download the image
        response = requests.get(image_url)
        img = Image.open(BytesIO(response.content))
        
        # Create a drawing context with alpha channel support
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        draw = ImageDraw.Draw(img)
        
        # Calculate font size based on image dimensions - larger for meme style
        font_size = int(img.width / font_size_factor)  # Bigger font for meme style
        
        # Try to load Impact font (classic meme font), fall back to others if not available
        try:
            # Try Impact first (classic meme font)
            font = ImageFont.truetype("impact.ttf", font_size)
        except IOError:
            try:
                # Try Arial Bold as second option
                font = ImageFont.truetype("arialbd.ttf", font_size)
            except IOError:
                try:
                    # Try DejaVuSans-Bold as third option (often available on Linux)
                    font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
                except IOError:
                    # Fall back to default if no suitable fonts are found
                    font = ImageFont.load_default()
                    font_size = int(img.width / 20)  # Adjust size for default font
        
        # Wrap text to fit image width
        max_chars_per_line = max(font_size_factor, int(img.width / (font_size * 0.6)))  # Estimate chars that fit
        lines = textwrap.wrap(text.upper(), width=max_chars_per_line)  # UPPERCASE for meme style
        
        # Calculate text position (bottom of image with padding)
        y_position = img.height - (len(lines) * font_size) - 30
        
        # Add semi-transparent background for better readability
        text_height = len(lines) * font_size + 30
        draw.rectangle(
            [(0, y_position - 10), (img.width, img.height)],
            fill=(0, 0, 0, 180)  # Semi-transparent black
        )
        
        # Draw text with outline effect
        outline_width = max(1, int(font_size / 15))  # Scale outline to font size
        
        for line in lines:
            # Get text width for centering
            try:
                line_width = draw.textlength(line, font=font)
            except AttributeError:
                # For older PIL versions
                line_width = font.getmask(line).getbbox()[2]
                
            x_position = (img.width - line_width) / 2  # Center text
            
            # Draw the black outline by offsetting the text in multiple directions
            for offset_x in range(-outline_width, outline_width + 1):
                for offset_y in range(-outline_width, outline_width + 1):
                    if offset_x != 0 or offset_y != 0:  # Skip the center (will be drawn in white)
                        draw.text(
                            (x_position + offset_x, y_position + offset_y), 
                            line, 
                            font=font, 
                            fill=(0, 0, 0)  # Black outline
                        )
            
            # Draw the white text on top of the outline
            draw.text(
                (x_position, y_position), 
                line, 
                font=font, 
                fill=(255, 255, 255)  # White text
            )
            
            y_position += font_size
        
        # Convert to base64 for sending to client
        buffered = BytesIO()
        img = img.convert('RGB')  # Convert back to RGB for JPEG
        img.save(buffered, format="JPEG", quality=95)
        img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
        
        return f"data:image/jpeg;base64,{img_str}"
    
    except Exception as e:
        print(f"Error processing image: {e}")
        return image_url  # Return original URL if processing fails

# Route to handle the form submission and translation
@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("index.html")

@app.route("/stream_translation", methods=["POST"])
def stream_translation():
    sentence = request.form["sentence"]
    
    def generate():
        # First yield the original sentence
        yield f"data: {json.dumps({'type': 'translation', 'language': 'Original', 'text': sentence})}\n\n"
        
        # Get the translations through 30 random languages
        languages = [lang.code for lang in translator.get_target_languages()]
        random_languages = random.sample([lang for lang in languages if lang != "PT-BR"], 30)
        
        # Initialize translated_text with the original sentence
        current_text = sentence
        
        for lang in random_languages:
            current_text = translator.translate_text(current_text, target_lang=lang).text
            yield f"data: {json.dumps({'type': 'translation', 'language': lang, 'text': current_text})}\n\n"
        
        # Finally, translate back to PT-BR
        final_translation = translator.translate_text(current_text, target_lang="PT-BR").text
        yield f"data: {json.dumps({'type': 'translation', 'language': 'PT-BR', 'text': final_translation})}\n\n"
        yield f"data: {json.dumps({'type': 'final', 'text': final_translation})}\n\n"
        
        # Get the image, add text to it, and send it as the last event
        image_url = get_image_url(sentence)
        if image_url:
            # Add the final translation text to the image
            processed_image = add_text_to_image(image_url, final_translation)
            yield f"data: {json.dumps({'type': 'image', 'url': processed_image})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'image', 'url': None})}\n\n"
    
    return Response(generate(), mimetype="text/event-stream")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)