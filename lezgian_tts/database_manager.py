import psycopg2
from typing import Dict, Any, Optional

class DatabaseManager:
    def __init__(self, db_config: Dict[str, Any]):
        self.db_config = db_config

    def connect(self):
        return psycopg2.connect(**self.db_config)

    def execute_query(self, query: str, params: tuple = (), conn=None):
        own_conn = False
        if conn is None:
            conn = self.connect()
            own_conn = True
        cur = conn.cursor()
        try:
            cur.execute(query, params)
            if cur.description is not None:
                result = cur.fetchall()
            else:
                if own_conn:
                    conn.commit()
                result = None
            return result
        finally:
            cur.close()
            if own_conn:
                conn.close()

    def close_connection(self, conn):
        if conn:
            conn.close() 