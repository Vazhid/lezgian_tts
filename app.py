from flask import Flask, request, send_file, jsonify
from lezgian_tts import LezgianTTS
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

tts = LezgianTTS(logger=logger)

executor = ThreadPoolExecutor(max_workers=4)

task_results = {}
task_lock = threading.Lock()

db_config = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "mydb"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres")
}

AUDIO_HISTORY_DIR = Path(__file__).parent / 'audio_history'
AUDIO_HISTORY_DIR.mkdir(exist_ok=True)

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

def process_synthesis(text, language, task_id, request_db_id):
    """Функция для обработки синтеза речи в отдельном потоке"""
    start_time = datetime.now()
    output_filepath = None
    
    if request_db_id is not None:
        conn = None
        cur = None
        try:
            conn = psycopg2.connect(**db_config)
            cur = conn.cursor()
            cur.execute("""
                UPDATE SpeechSynthesisRequest
                SET status = %s, processing_start_dttm = %s
                WHERE id = %s
            """, ('processing', start_time, request_db_id))
            conn.commit()
            logger.info(f"Updated status for DB request {request_db_id} to 'processing'")
        except Exception as db_err:
            logger.error(f"Error updating status to 'processing' for DB request {request_db_id}: {str(db_err)}")
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    try:
        logger.info(f"Processing synthesis task {task_id} (DB ID: {request_db_id}) for text: '{text[:50]}...' (language: {language})")
        
        output_filename = f'{task_id}.wav'
        output_filepath = AUDIO_HISTORY_DIR / output_filename
        
        if not tts.save_to_file(text, str(output_filepath)):
            logger.error(f"Failed to synthesize speech for task {task_id} (DB ID: {request_db_id})")
            
            if request_db_id is not None:
                 conn = None
                 cur = None
                 try:
                     conn = psycopg2.connect(**db_config)
                     cur = conn.cursor()
                     cur.execute("""
                         UPDATE SpeechSynthesisRequest
                         SET status = %s, processing_end_dttm = %s
                         WHERE id = %s
                     """, ('error', datetime.now(), request_db_id))
                     conn.commit()
                     logger.info(f"Updated status for DB request {request_db_id} to 'error'")
                 except Exception as db_err:
                     logger.error(f"Error updating status to 'error' for DB request {request_db_id}: {str(db_err)}")
                 finally:
                     if cur:
                         cur.close()
                     if conn:
                         conn.close()

            with task_lock:
                task_results[task_id] = {'status': 'error', 'error': 'Ошибка синтеза речи'}
            if output_filepath and output_filepath.exists():
                try:
                    output_filepath.unlink()
                    logger.debug(f"Removed incomplete audio file: {output_filepath}")
                except Exception as e:
                    logger.error(f"Error removing incomplete audio file: {str(e)}")

            return
        
        try:
            with open(output_filepath, 'rb') as f:
                audio_data = f.read()
        except Exception as e:
             logger.error(f"Error reading audio file {output_filepath}: {str(e)}")
             audio_data = None

        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Task {task_id} (DB ID: {request_db_id}) completed in {duration:.2f} seconds")
        
        if request_db_id is not None:
             conn = None
             cur = None
             try:
                 conn = psycopg2.connect(**db_config)
                 cur = conn.cursor()
                 
                 cur.execute("""
                     UPDATE SpeechSynthesisRequest
                     SET status = %s, processing_end_dttm = %s
                     WHERE id = %s
                 """, ('success', datetime.now(), request_db_id))
                 
                 relative_filepath = str(output_filepath.relative_to(Path(__file__).parent))
                 cur.execute("""
                     INSERT INTO SpeechSynthesisResult 
                     (request_id, audio_file_path, duration_seconds, characters_processed)
                     VALUES (%s, %s, %s, %s)
                 """, (request_db_id, relative_filepath, duration, len(text)))

                 conn.commit()
                 logger.info(f"Updated status for DB request {request_db_id} to 'success' and saved result")
             except Exception as db_err:
                 logger.error(f"Error updating status to 'success' and saving result for DB request {request_db_id}: {str(db_err)}")
             finally:
                 if cur:
                     cur.close()
                 if conn:
                     conn.close()

        with task_lock:
            task_results[task_id] = {
                'status': 'success',
                'audio_data': audio_data,
                'duration': duration,
                'audio_path': str(output_filepath.relative_to(AUDIO_HISTORY_DIR))
            }
    
    except Exception as e:
        logger.error(f"Error in synthesis task {task_id} (DB ID: {request_db_id}): {str(e)}", exc_info=True)
        
        if request_db_id is not None:
             conn = None
             cur = None
             try:
                 conn = psycopg2.connect(**db_config)
                 cur = conn.cursor()
                 cur.execute("""
                     UPDATE SpeechSynthesisRequest
                     SET status = %s, processing_end_dttm = %s
                     WHERE id = %s
                 """, ('error', datetime.now(), request_db_id))
                 conn.commit()
                 logger.info(f"Updated status for DB request {request_db_id} to 'error' due to exception")
             except Exception as db_err:
                 logger.error(f"Error updating status to 'error' after exception for DB request {request_db_id}: {str(db_err)}")
             finally:
                 if cur:
                     cur.close()
                 if conn:
                     conn.close()

        with task_lock:
            task_results[task_id] = {'status': 'error', 'error': str(e)}
    
    finally:
        pass

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
        
        conn = None
        cur = None
        try:
            conn = psycopg2.connect(**db_config)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO SpeechSynthesisRequest 
                (user_id, input_text, status, create_dttm, language_code)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
            """, (user_id, text, 'queued', datetime.now(), language))
            
            request_db_id = cur.fetchone()[0]
            conn.commit()
            logger.info(f"Created DB entry for synthesis request {request_db_id} (Task ID: {task_id})")
            
        except Exception as db_err:
            logger.error(f"Error saving synthesis request to DB: {str(db_err)}")
            request_db_id = None
            
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

        logger.info(f"Queueing synthesis task {task_id} for text: '{text[:50]}...' (language: {language})")
        
        executor.submit(process_synthesis, text, language, task_id, request_db_id)
        
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
        with task_lock:
            result = task_results.get(task_id)
        
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
        
        with task_lock:
            task_results.pop(task_id, None)
        
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
        conn = psycopg2.connect(**db_config)
        cur = conn.cursor()
        cur.execute("""
            SELECT 1
            FROM SpeechSynthesisResult res
            JOIN SpeechSynthesisRequest req ON res.request_id = req.id
            WHERE res.audio_file_path = %s AND req.user_id = %s
        """, (str(Path('audio_history') / filename), current_user.id))
        
        if cur.fetchone():
            is_authorized = True

    except Exception as db_err:
        logger.error(f"Error checking audio file access for user {current_user.id}: {str(db_err)}")

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    if not is_authorized:
         return jsonify({'error': 'Unauthorized access to audio file'}), 403

    if audio_file_path.exists():
        return send_file(str(audio_file_path), mimetype='audio/wav')
    else:
        return jsonify({'error': 'Audio file not found'}), 404

if __name__ == '__main__':
    logger.info("Starting application")
    app.run(debug=True, host='0.0.0.0', port=1010)
