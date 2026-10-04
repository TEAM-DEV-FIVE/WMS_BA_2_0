# apps/desktop/views/home_screen.py
# Màn hình thử nghiệm. UI03, UI04... sẽ tạo thêm file màn hình giống thế này.
import uuid
from tkinter import *

FONT = ("Segoe UI", 11)


class HomeScreen(Frame):
    def __init__(self, parent, app):
        Frame.__init__(self, parent, bg="white", padx=30, pady=20)
        self.app = app
        self.count = 0
        self.unknown_key = app.store.last_unknown_key()

        Label(self, text="Thử API client", bg="white", fg="#1F3A5F",
              font=("Segoe UI", 14, "bold")).grid(row=0, column=0, columnspan=2,
                                                  pady=(0, 10))

        self.make_button("1. Gửi lệnh bình thường", "#2E7D32", self.send_normal, 1)
        self.make_button("2. Gửi lệnh - giả lập MẤT PHẢN HỒI", "#E65100",
                         self.send_lost, 2)
        self.make_button("3. Tra kết quả thao tác UNKNOWN", "#1565C0",
                         self.check_unknown, 3)
        self.make_button("4. Gửi lại UNKNOWN (cùng key)", "#1565C0",
                         self.retry_unknown, 4)

        Button(self, text="Bấm thử (cửa sổ không đơ)", command=self.click_test,
               bg="#757575", fg="white", font=FONT, relief="flat", cursor="hand2",
               activebackground="#757575", activeforeground="white").grid(
            row=5, column=0, pady=(15, 5), ipadx=8, ipady=3)
        self.count_label = Label(self, text="Số lần bấm: 0", bg="white", font=FONT)
        self.count_label.grid(row=5, column=1, pady=(15, 5))

        self.result_label = Label(self, text="Chưa gửi gì", fg="#1565C0",
                                  bg="#F0F2F5", font=("Segoe UI", 11, "bold"),
                                  width=42, height=2, wraplength=360)
        self.result_label.grid(row=6, column=0, columnspan=2, pady=(10, 0))

        if self.unknown_key:
            self.result_label.config(
                text="Có thao tác UNKNOWN từ lần trước, bấm nút 3 để tra.")

    def make_button(self, text, color, command, row):
        Button(self, text=text, command=command, bg=color, fg="white", font=FONT,
               width=38, relief="flat", cursor="hand2", activebackground=color,
               activeforeground="white").grid(row=row, column=0, columnspan=2,
                                              pady=5, ipady=4)

    def new_payload(self):
        # execution_key sinh MỘT lần và nằm trong payload, nên gửi lại vẫn y nguyên
        return {"expected_version": 1, "execution_key": str(uuid.uuid4()), "lines": []}

    def send_normal(self):
        self.app.send_command("/receipts/DEMO/post", self.new_payload(), self.show_result)

    def send_lost(self):
        self.app.api.mock_lose_response = True
        self.app.send_command("/receipts/DEMO/post", self.new_payload(), self.show_result)

    def check_unknown(self):
        if self.unknown_key is None:
            self.result_label.config(text="Không có thao tác UNKNOWN nào.")
            return
        self.app.check_operation(self.unknown_key, self.show_result)

    def retry_unknown(self):
        if self.unknown_key is None:
            self.result_label.config(text="Không có thao tác UNKNOWN nào.")
            return
        self.app.retry_operation(self.unknown_key, self.show_result)

    def click_test(self):
        self.count = self.count + 1
        self.count_label.config(text="Số lần bấm: " + str(self.count))

    def show_result(self, status, data):
        if status == "POSTED":
            self.unknown_key = None
            self.result_label.config(text="POSTED - server đã ghi sổ", fg="#2E7D32")
        elif status == "UNKNOWN":
            self.unknown_key = data
            self.result_label.config(
                text="UNKNOWN - chưa rõ kết quả. Bấm nút 3 hoặc 4.", fg="#E65100")
        elif status == "NOT_FOUND":
            self.result_label.config(
                text="Server chưa có kết quả. Nếu cần, gửi lại CÙNG key (nút 4).",
                fg="#E65100")
        else:
            self.result_label.config(
                text="Bị từ chối: " + data.code + " - " + data.message, fg="#C62828")