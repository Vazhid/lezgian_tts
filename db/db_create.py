import psycopg2
from dotenv import load_dotenv
import os
import sys

if "../../" not in sys.path:
    sys.path.append("../../")

load_dotenv()

db_config = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "mydb"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "postgres")
}

def create_database_structure(conf: dict):
    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(**conf)
        cursor = conn.cursor()
        
        print("Успешное подключение к базе данных")
        
        print("Удаление существующих таблиц...")
        cursor.execute("DROP TABLE IF EXISTS \"User\" CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS Session CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS OAuthToken CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS SpeechSynthesisResult CASCADE;")
        cursor.execute("DROP TABLE IF EXISTS SpeechSynthesisRequest CASCADE;")
        conn.commit()
        print("Существующие таблицы удалены (если были)")
        
        cursor.execute("""
            CREATE TABLE "User" (
                id SERIAL PRIMARY KEY,
                username VARCHAR(32) NOT NULL,
                password TEXT NOT NULL,
                last_login TIMESTAMP,
                date_joined TIMESTAMP NOT NULL,
                is_superuser INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1
            );
        """)
        
        cursor.execute("""
            CREATE TABLE Session (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                session_key VARCHAR(64) NOT NULL,
                session_data VARCHAR(64),
                expire_date TIMESTAMP NOT NULL,
                CONSTRAINT fk_user
                    FOREIGN KEY(user_id) 
                    REFERENCES "User"(id)
                    ON DELETE CASCADE
            );
        """)
        
        cursor.execute("""
            CREATE TABLE OAuthToken (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                jti VARCHAR(64) NOT NULL,
                expires TIMESTAMP NOT NULL,
                created TIMESTAMP NOT NULL,
                updated TIMESTAMP NOT NULL,
                CONSTRAINT fk_user
                    FOREIGN KEY(user_id) 
                    REFERENCES "User"(id)
                    ON DELETE CASCADE
            );
        """)
        
        cursor.execute("""
            CREATE TABLE SpeechSynthesisRequest (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                input_text TEXT NOT NULL,
                status VARCHAR(16) NOT NULL,
                create_dttm TIMESTAMP NOT NULL,
                processing_start_dttm TIMESTAMP,
                processing_end_dttm TIMESTAMP,
                voice_model VARCHAR(32),
                output_format VARCHAR(16),
                language_code VARCHAR(8),
                CONSTRAINT fk_user
                    FOREIGN KEY(user_id) 
                    REFERENCES "User"(id)
                    ON DELETE CASCADE
            );
        """)
        
        cursor.execute("""
            CREATE TABLE SpeechSynthesisResult (
                id SERIAL PRIMARY KEY,
                request_id INTEGER NOT NULL,
                audio_file_path VARCHAR(255) NOT NULL,
                duration_seconds FLOAT NOT NULL,
                characters_processed INTEGER NOT NULL,
                CONSTRAINT fk_request
                    FOREIGN KEY(request_id) 
                    REFERENCES SpeechSynthesisRequest(id)
                    ON DELETE CASCADE
            );
        """)
        
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_username ON \"User\"(username);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_user ON Session(user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_oauth_user ON OAuthToken(user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_synth_user ON SpeechSynthesisRequest(user_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_result_request ON SpeechSynthesisResult(request_id);")
        
        conn.commit()
        print("Структура базы данных успешно создана")
        
    except Exception as e:
        print(f"Ошибка при создании структуры БД: {e}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    create_database_structure(
        conf=db_config
    )
