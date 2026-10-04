# apps/desktop/worker.py
# Chạy việc chậm (gọi mạng) ở luồng nền để cửa sổ không bị đơ.
import queue
import threading


class Worker:
    def __init__(self, root):
        self.root = root
        self.results = queue.Queue()
        self.check_results()          # bắt đầu kiểm tra hàng đợi

    def run(self, task, on_done, on_error):
        def job():                    # chạy ở luồng nền
            try:
                value = task()
                self.results.put((on_done, value))
            except Exception as e:
                self.results.put((on_error, e))
        threading.Thread(target=job, daemon=True).start()

    def check_results(self):          # chạy ở luồng chính, mỗi 100ms
        while not self.results.empty():
            callback, value = self.results.get()
            callback(value)
        self.root.after(100, self.check_results)