from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Dict, Optional, Any
from datetime import datetime

class TaskManager:
    def __init__(self, tts, audio_manager, db_manager):
        self.tts = tts
        self.audio_manager = audio_manager
        self.db_manager = db_manager
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.task_results: Dict[str, Any] = {}
        self.task_lock = Lock()

    def submit_task(self, task_id: str, text: str, language: str, user_id: int):
        conn = self.db_manager.connect()
        request_db_id = None
        try:
            result = self.db_manager.execute_query(
                """
                INSERT INTO SpeechSynthesisRequest 
                (user_id, input_text, status, create_dttm, language_code)
                VALUES (%s, %s, %s, %s, %s) RETURNING id
                """,
                (user_id, text, 'queued', datetime.now(), language),
                conn=conn
            )
            conn.commit()
            if result and len(result) > 0:
                request_db_id = result[0][0]
        except Exception as db_err:
            with self.task_lock:
                self.task_results[task_id] = {'status': 'error', 'error': str(db_err)}
            conn.close()
            return
        self.executor.submit(self.process_synthesis, text, language, task_id, request_db_id, conn)

    def get_task_status(self, task_id: str) -> Dict:
        with self.task_lock:
            return self.task_results.get(task_id, {'status': 'processing'})

    def process_synthesis(self, text: str, language: str, task_id: str, request_db_id: Optional[int], conn):
        start_time = datetime.now()
        output_filename = f'{task_id}.wav'
        output_filepath = self.audio_manager.get_audio_path(output_filename)

        if request_db_id is not None:
            self.db_manager.execute_query(
                """
                UPDATE SpeechSynthesisRequest
                SET status = %s, processing_start_dttm = %s
                WHERE id = %s
                """,
                ('processing', start_time, request_db_id),
                conn=conn
            )
            conn.commit()
        try:
            success = self.tts.save_to_file(text, str(output_filepath))
            if not success:
                if request_db_id is not None:
                    self.db_manager.execute_query(
                        """
                        UPDATE SpeechSynthesisRequest
                        SET status = %s, processing_end_dttm = %s
                        WHERE id = %s
                        """,
                        ('error', datetime.now(), request_db_id),
                        conn=conn
                    )
                    conn.commit()
                with self.task_lock:
                    self.task_results[task_id] = {'status': 'error', 'error': 'Ошибка синтеза речи'}
                self.audio_manager.delete_audio(output_filename)
                conn.close()
                return
            with open(output_filepath, 'rb') as f:
                audio_data = f.read()
            duration = (datetime.now() - start_time).total_seconds()
            if request_db_id is not None:
                self.db_manager.execute_query(
                    """
                    UPDATE SpeechSynthesisRequest
                    SET status = %s, processing_end_dttm = %s
                    WHERE id = %s
                    """,
                    ('success', datetime.now(), request_db_id),
                    conn=conn
                )
                relative_filepath = str(output_filepath.relative_to(output_filepath.parent.parent))
                self.db_manager.execute_query(
                    """
                    INSERT INTO SpeechSynthesisResult 
                    (request_id, audio_file_path, duration_seconds, characters_processed)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (request_db_id, relative_filepath, duration, len(text)),
                    conn=conn
                )
                conn.commit()
            with self.task_lock:
                self.task_results[task_id] = {
                    'status': 'success',
                    'audio_data': audio_data,
                    'duration': duration,
                    'audio_path': str(output_filepath.name)
                }
        except Exception as e:
            if request_db_id is not None:
                self.db_manager.execute_query(
                    """
                    UPDATE SpeechSynthesisRequest
                    SET status = %s, processing_end_dttm = %s
                    WHERE id = %s
                    """,
                    ('error', datetime.now(), request_db_id),
                    conn=conn
                )
                conn.commit()
            with self.task_lock:
                self.task_results[task_id] = {'status': 'error', 'error': str(e)}
        finally:
            conn.close() 