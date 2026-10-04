# apps/desktop/main.py
# Khung ứng dụng: cửa sổ chính, thanh trạng thái, đổi màn hình, gửi lệnh qua API.
import uuid
from tkinter import *
from tkinter import messagebox

from api.client import ApiClient, ApiError, UnknownResult
from local_store.pending import PendingStore
from worker import Worker
from views.home_screen import HomeScreen


class App:
    def __init__(self):
        self.root = Tk()
        self.root.title("WMS - Quản lý kho")
        self.root.geometry("800x540")
        self.root.configure(bg="#F0F2F5")

        # use_mock=True: dùng server giả. Khi backend thật xong, đổi thành False
        self.api = ApiClient("https://wms.example.internal/api/v1", use_mock=True)
        self.store = PendingStore()
        self.worker = Worker(self.root)

        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # Hàng 0: thanh tiêu đề màu xanh đậm
        header = Frame(self.root, bg="#1F3A5F")
        header.grid(row=0, column=0, sticky="we")
        header.grid_columnconfigure(0, weight=1)
        Label(header, text="WMS - Quản lý kho", bg="#1F3A5F", fg="white",
              font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w",
                                                  padx=20, pady=12)
        Label(header, text="Chế độ thử (server giả)", bg="#1F3A5F", fg="#FFD166",
              font=("Segoe UI", 10)).grid(row=0, column=1, padx=20)

        # Hàng 1: vùng nội dung
        self.content = Frame(self.root, bg="#F0F2F5")
        self.content.grid(row=1, column=0)

        # Hàng 2: thanh trạng thái
        self.status = Label(self.root, text="Sẵn sàng", anchor="w", bg="#2B2B2B",
                            fg="white", font=("Segoe UI", 10), padx=10, pady=4)
        self.status.grid(row=2, column=0, sticky="we")

        self.screen = None
        self.store.mark_sending_as_unknown()   # lần chạy trước tắt giữa chừng
        self.show_screen(HomeScreen)

    def show_screen(self, screen_class):
        if self.screen is not None:
            self.screen.destroy()
        self.screen = screen_class(self.content, self)
        self.screen.grid(row=0, column=0, padx=20, pady=20)

    def set_status(self, text):
        self.status.config(text=text)

    # ---- Gửi lệnh mới: tạo key, LƯU trước, rồi mới gửi ----
    def send_command(self, endpoint, payload, on_finish):
        key = str(uuid.uuid4())
        self.store.save_pending(key, self.api.base_url, self.api.user_id,
                                endpoint, payload)
        self.send_with_key(key, endpoint, payload, on_finish)

    def send_with_key(self, key, endpoint, payload, on_finish):
        self.store.set_state(key, "SENDING")
        self.set_status("Đang gửi...")

        def task():                          # luồng nền
            return self.api.post_command(endpoint, payload, key)

        def done(result):                    # luồng chính
            self.store.set_state(key, "COMMITTED", result)
            self.set_status("POSTED")
            on_finish("POSTED", result)

        def fail(error):
            if isinstance(error, UnknownResult):
                self.store.set_state(key, "UNKNOWN")
                self.set_status("UNKNOWN - chưa rõ kết quả")
                on_finish("UNKNOWN", key)
            elif isinstance(error, ApiError):
                self.store.set_state(key, "CONFLICT")
                self.set_status("Bị từ chối: " + error.code)
                on_finish("ERROR", error)
            else:
                messagebox.showerror("Lỗi", str(error))

        self.worker.run(task, done, fail)

    # ---- Tra kết quả thao tác cũ ----
    def check_operation(self, key, on_finish):
        self.set_status("Đang tra kết quả...")

        def task():
            return self.api.get_operation(key)

        def done(result):
            if result is None:
                self.set_status("NOT_FOUND")
                on_finish("NOT_FOUND", key)
            else:
                self.store.set_state(key, "COMMITTED", result)
                self.set_status("POSTED")
                on_finish("POSTED", result)

        def fail(error):
            messagebox.showerror("Lỗi", str(error))

        self.worker.run(task, done, fail)

    # ---- Gửi lại: LUÔN dùng đúng key và payload cũ ----
    def retry_operation(self, key, on_finish):
        endpoint, payload = self.store.get_operation(key)
        self.send_with_key(key, endpoint, payload, on_finish)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()