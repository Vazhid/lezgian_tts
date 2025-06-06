from flask import Flask, request, send_file, jsonify
from lezgian_tts import LezgianTTS, AudioManager, TaskManager, DatabaseManager
import os
import tempfile
import logging
from flask_cors import CORS
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from pathlib import Path
from pydub import AudioSegment
import io

def setup_logger():
    logger = logging.getLogger('LezgianTTSApp')
    logger.setLevel(logging.INFO)
    logger.propagate = True
    
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    return logger

logger = setup_logger()

app = Flask(__name__, static_folder='ui', static_url_path='')
CORS(app)
app.secret_key = os.urandom(24)

login_manager = LoginManager()
login_manager.init_app(app)

db_config = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "mydb"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres")
}

AUDIO_HISTORY_DIR = Path(__file__).parent / 'audio_history'
AUDIO_HISTORY_DIR.mkdir(exist_ok=True)

tts = LezgianTTS(logger=logger)
audio_manager = AudioManager(AUDIO_HISTORY_DIR)
db_manager = DatabaseManager(db_config)
task_manager = TaskManager(tts, audio_manager, db_manager)

executor = ThreadPoolExecutor(max_workers=4)

task_results = {}
task_lock = threading.Lock()

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        cur.execute("SELECT id, username FROM \"User\" WHERE id = %s", (user_id,))
        user_data = cur.fetchone()
        if user_data:
            return User(user_data[0], user_data[1])
    except Exception as e:
        logger.error(f"Error loading user: {str(e)}")
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()
    return None

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Необходимо указать имя пользователя и пароль'}), 400
        
        if len(password) < 8:
            return jsonify({'error': 'Пароль должен содержать не менее 8 символов'}), 400
            
        if not any(char.isdigit() for char in password):
             return jsonify({'error': 'Пароль должен содержать хотя бы одну цифру'}), 400

        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        
        cur.execute("SELECT id FROM \"User\" WHERE username = %s", (username,))
        if cur.fetchone():
            return jsonify({'error': 'Пользователь с таким именем уже существует'}), 400
        
        hashed_password = generate_password_hash(password)
        cur.execute(
            "INSERT INTO \"User\" (username, password, date_joined, is_active) VALUES (%s, %s, %s, %s) RETURNING id",
            (username, hashed_password, datetime.now(), 1)
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        
        return jsonify({'status': 'success', 'user_id': user_id})
        
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Необходимо указать имя пользователя и пароль'}), 400
        
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        cur.execute("SELECT id, username, password FROM \"User\" WHERE username = %s", (username,))
        user_data = cur.fetchone()
        
        if user_data and check_password_hash(user_data[2], password):
            user = User(user_data[0], user_data[1])
            login_user(user)
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Неверные учетные данные'}), 401
            
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

@app.route('/api/logout')
@login_required
def logout():
    logout_user()
    return jsonify({'status': 'success'})

@app.route('/api/history')
@login_required
def get_history():
    try:
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                s.create_dttm,
                s.input_text,
                s.language_code,
                s.status,
                r.audio_file_path,
                r.duration_seconds
            FROM SpeechSynthesisRequest s
            LEFT JOIN SpeechSynthesisResult r ON s.id = r.request_id
            WHERE s.user_id = %s
            ORDER BY s.create_dttm DESC
            LIMIT 50
        """, (current_user.id,))
        
        history = []
        for row in cur.fetchall():
            audio_url = None
            if row[4]:
                audio_filename = Path(row[4]).name
                audio_url = f'http://127.0.0.1:1010/api/audio/{audio_filename}'

            history.append({
                'date': row[0].strftime('%d.%m.%Y %H:%M'),
                'text': row[1],
                'language': row[2],
                'status': row[3],
                'audio_path': audio_url,
                'duration': row[5]
            })
            
        return jsonify({'history': history})
        
    except Exception as e:
        logger.error(f"Error getting history: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

@app.before_request
def log_request():
    logger.info(f"Request: {request.method} {request.path}")

@app.after_request
def log_response(response):
    logger.info(f"Response: {response.status_code}")
    return response

@app.route('/')
def home():
    logger.info("Serving index page")
    return app.send_static_file('index.html')

@app.route('/api/synthesize', methods=['POST'])
@login_required
def synthesize():
    try:
        data = request.get_json()
        logger.debug(f"Request data: {data}")
        
        if not data or 'text' not in data:
            logger.warning("No text in request")
            return jsonify({'error': 'Не указан текст в запросе'}), 400
        
        text = data['text']
        language = data.get('language', 'lez')
        user_id = current_user.id
        
        task_id = str(uuid.uuid4())
        logger.info(f"Queueing synthesis task {task_id} for text: '{text[:50]}...' (language: {language})")
        task_manager.submit_task(task_id, text, language, user_id)
        
        return jsonify({
            'task_id': task_id,
            'status': 'queued'
        })
    
    except Exception as e:
        logger.error(f"Error in synthesize: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/api/task/<task_id>', methods=['GET'])
def get_task_status(task_id):
    try:
        with task_manager.task_lock:
            result = task_manager.task_results.get(task_id)
        
        if result is None:
            return jsonify({
                'status': 'processing',
                'task_id': task_id
            })
        
        if result['status'] == 'error':
            return jsonify({'status': 'error', 'error': result['error']}), 500
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file.write(result['audio_data'])
            temp_path = temp_file.name
        
        response = send_file(
            temp_path,
            mimetype='audio/wav',
            as_attachment=True,
            download_name='speech.wav'
        )
        
        os.unlink(temp_path)
        
        with task_manager.task_lock:
            task_manager.task_results.pop(task_id, None)
        
        return response
    
    except Exception as e:
        logger.error(f"Error checking task status: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health():
    logger.info("Health check")
    return jsonify({'status': 'ok'})

@app.route('/profile.html')
@login_required
def profile_page():
    logger.info("Serving profile page")
    response = app.send_static_file('profile.html')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/api/user', methods=['GET'])
@login_required
def get_user():
    try:
        return jsonify({'username': current_user.username})
    except Exception as e:
        logger.error(f"Error getting user info: {str(e)}")
        return jsonify({'error': 'Ошибка получения данных пользователя'}), 500

@app.route('/api/audio/<filename>', methods=['GET'])
@login_required
def serve_audio(filename):
    if '..' in filename or filename.startswith('/'):
        return jsonify({'error': 'Invalid filename'}), 400

    audio_file_path = AUDIO_HISTORY_DIR / filename

    conn = None
    cur = None
    is_authorized = False
    try:
        # Using db_manager to check access
        # NOTE: This check still opens a new connection. For better performance
        # especially if this endpoint is hit often, consider passing a connection
        # or using a connection pool properly.
        result = db_manager.execute_query(
            """
            SELECT 1
            FROM SpeechSynthesisResult res
            JOIN SpeechSynthesisRequest req ON res.request_id = req.id
            WHERE res.audio_file_path = %s AND req.user_id = %s
            """,
            (str(Path('audio_history') / filename), current_user.id)
        )
        if result and len(result) > 0:
            is_authorized = True

    except Exception as db_err:
        logger.error(f"Error checking audio file access for user {current_user.id}: {str(db_err)}")
        return jsonify({'error': 'Database error checking access'}), 500

    if not is_authorized:
         return jsonify({'error': 'Unauthorized access to audio file'}), 403

    if not audio_file_path.exists():
        return jsonify({'error': 'Audio file not found'}), 404

    requested_format = request.args.get('format', 'wav').lower()
    original_format = audio_file_path.suffix[1:].lower()

    if requested_format == original_format:
        # Serve original file
        mimetype = f'audio/{original_format}'
        download_name = f'speech.{original_format}'
        return send_file(str(audio_file_path), mimetype=mimetype, as_attachment=True, download_name=download_name)
    elif requested_format == 'mp3' and original_format == 'wav':
        # Convert WAV to MP3 and serve
        try:
            audio = AudioSegment.from_wav(audio_file_path)
            mp3_buffer = io.BytesIO()
            audio.export(mp3_buffer, format='mp3')
            mp3_buffer.seek(0)
            
            mimetype = 'audio/mpeg'
            download_name = f'speech.mp3'
            return send_file(mp3_buffer, mimetype=mimetype, as_attachment=True, download_name=download_name)
        except FileNotFoundError:
             logger.error("ffmpeg not found. Cannot convert to MP3.")
             return jsonify({'error': 'Audio conversion failed: ffmpeg not found.'}), 500
        except Exception as e:
            logger.error(f"Error during WAV to MP3 conversion: {str(e)}")
            return jsonify({'error': 'Audio conversion failed.'}), 500
    else:
        # Unsupported conversion or format
        return jsonify({'error': f'Unsupported format conversion requested: {original_format} to {requested_format}'}), 400

if __name__ == '__main__':
    logger.info("Starting application")
    app.run(debug=True, host='0.0.0.0', port=1010)
