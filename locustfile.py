from locust import HttpUser, task, between
import gevent

class WebsiteUser(HttpUser):
    wait_time = between(1, 5)

    @task
    def synthesize_and_poll(self):
        text_to_synthesize = """
            Гьар са шиир зи аял хьиз ,за хайи,
            Къалурда за,килиг лугьуз... таза я.        
        """
        language = "lez"

        synthesize_response = self.client.post("/api/synthesize", json={"text": text_to_synthesize, "language": language})

        if synthesize_response.status_code != 200:
            print(f"Synthesis request failed: {synthesize_response.status_code}")
            return

        task_id = synthesize_response.json()["task_id"]

        while True:
            status_response = self.client.get(f"/api/task/{task_id}")

            if status_response.status_code == 200:
                content_type = status_response.headers.get('Content-Type')
                if content_type == 'audio/wav':
                    print(f"Task {task_id} completed successfully.")
                    break
                elif content_type == 'application/json':
                        status_data = status_response.json()
                        if status_data.get('status') == 'error':
                            print(f"Task {task_id} failed: {status_data.get('error')}")
                            break
                        pass
                else:
                    print(f"Unexpected content type for task {task_id}: {content_type}")
                    break

            elif status_response.status_code != 404:
                    print(f"Polling task {task_id} failed: {status_response.status_code}")
                    break

            gevent.sleep(0.5)
