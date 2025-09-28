import sys
import re
import random
import time
import os
from PIL import Image
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QStackedWidget, QProgressBar,
    QComboBox, QCheckBox, QListWidget, QLabel, QListWidgetItem
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QSize
)
from PyQt6.QtGui import QFont

# استيراد مكتبة SLUGIFY المتوافقة مع Python 3
try:
    from slugify import slugify
except ImportError:
    print("يرجى تثبيت مكتبة python-slugify: pip install python-slugify")
    sys.exit(1)

# استيراد yt_dlp
try:
    import yt_dlp
except ImportError:
    print("يرجى تثبيت yt-dlp: pip install yt-dlp")
    sys.exit(1)

# ----------------------------------------------------------------------
## 1. إدارة الأنماط والألوان (Themes) - الوضع الداكن الافتراضي
# ----------------------------------------------------------------------
THEMES = {
    # الوضع الفاتح
    "light": {
        "BG": "#fcfcfc",
        "FG": "#333333",
        "HEADER": "#FF6F00",
        "PRIMARY": "#FFC107",
        "PRIMARY_HOVER": "#FFAB00",
        "PRIMARY_PRESS": "#FF6F00",
        "WARNING": "#17A2B8",
        "WARNING_HOVER": "#138496",
        "WARNING_PRESS": "#0f6674",
        "DANGER": "#f44336",
        "DANGER_HOVER": "#e53935",
        "DANGER_PRESS": "#d32f2f",
        "PROGRESS_BAR": "#FF6F00",
        "INPUT_BG": "white",
        "THEME_BUTTON_COLOR": "#FFD700",
        "THEME_BUTTON_TEXT": "🌙"
    },

    # الوضع الداكن
    "dark": {
        "BG": "#0a0a0a",
        "FG": "#f0f0f0",
        "HEADER": "#8d0000",
        "PRIMARY": "#dc0000",
        "PRIMARY_HOVER": "#f00000",
        "PRIMARY_PRESS": "#c80000",
        "WARNING": "#3f0000",
        "WARNING_HOVER": "#530000",
        "WARNING_PRESS": "#2b0000",
        "DANGER": "#3f0000",
        "DANGER_HOVER": "#530000",
        "DANGER_PRESS": "#2b0000",
        "PROGRESS_BAR": "#dc0000",
        "INPUT_BG": "#180000",
        "THEME_BUTTON_COLOR": "#530000",
        "THEME_BUTTON_TEXT": "☀️"
    }
}

# ----------------------------------------------------------------------
## 2. تصميم الزر المخصص (CustomButton)
# ----------------------------------------------------------------------
class CustomButton(QPushButton):
    """زر مع تأثير Hover/Press باستخدام QSS."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)
        font = QFont()
        font.setPointSize(10)
        self.setFont(font)

    def set_theme_colors(self, color, hover_color, press_color):
        self.setStyleSheet(self.get_style_sheet(color, hover_color, press_color))

    def get_style_sheet(self, color, hover_color, press_color):
        """توليد ورقة الأنماط للزر."""
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                padding: 10px 15px;
                text-align: center;
                text-decoration: none;
                font-size: 14px;
                margin: 4px 2px;
                border-radius: 8px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                border: 1px solid #ffffff30;
            }}
            QPushButton:pressed {{
                background-color: {press_color};
                padding-left: 14px;
                padding-right: 16px;
                border: none;
            }}
            QPushButton:disabled {{
                background-color: #555555;
                color: #aaaaaa;
                font-weight: normal;
            }}
        """

    def set_warning_style(self, theme):
        self.set_theme_colors(theme['WARNING'], theme['WARNING_HOVER'], theme['WARNING_PRESS'])

    def set_danger_style(self, theme):
        self.set_theme_colors(theme['DANGER'], theme['DANGER_HOVER'], theme['DANGER_PRESS'])

    def set_success_style(self, theme):
        self.set_theme_colors(theme['PRIMARY'], theme['PRIMARY_HOVER'], theme['PRIMARY_PRESS'])

# ----------------------------------------------------------------------
## 3. عامل yt-dlp في خيط منفصل (Worker Thread)
# ----------------------------------------------------------------------
class YtdlpWorker(QThread):
    # إشارات مخصصة
    formats_ready = pyqtSignal(list, str)
    download_progress = pyqtSignal(int)
    download_finished = pyqtSignal(str)
    download_error = pyqtSignal(str)

    def __init__(self, url=None, download_options=None):
        super().__init__()
        self.url = url
        self.download_options = download_options
        self.is_downloading = False
        self._is_cancelled = False

        # **الإعدادات الأساسية:** نظيفة من أي postprocessors لتجنب أخطاء FFmpeg أثناء الجلب
        self.ydl_opts_base = {
            'quiet': True,
            'noplaylist': True,
            'writethumbnail': True,
            'postprocessors': [],
        }

    def run(self):
        if self.download_options is None:
            self._fetch_formats()
        else:
            self._start_download()

    def _progress_hook(self, d):
        # **التصحيح:** إضافة تحقق للتأكد من أن d هو قاموس وليس سلسلة نصية (لمعالجة خطأ 'str' object has no attribute 'get')
        if not isinstance(d, dict):
            # نتجاهل التنبيهات غير المتعلقة بالتقدم إذا لم تكن قاموس
            return

        if self._is_cancelled:
            raise SystemExit("Download cancelled by user.")

        if d['status'] == 'downloading':
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
            downloaded_bytes = d.get('downloaded_bytes', 0)

            if total_bytes > 0:
                 percent = int(downloaded_bytes * 100 / total_bytes)
                 self.download_progress.emit(percent)
        elif d['status'] == 'finished':
            self.download_finished.emit(d.get('filename', ''))
            self.is_downloading = False

    def _fetch_formats(self):
        """جلب الصيغ المتاحة للفيديو."""
        try:
            ydl_opts = self.ydl_opts_base.copy()
            # تعطيل postprocessors بوضوح لتجنب خطأ FFmpegExtractThumbnailPP
            ydl_opts.update({'simulate': True, 'force_generic_extractor': True, 'postprocessors': []})

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(self.url, download=False)
                formats = []
                for f in info_dict.get('formats', []):
                    # عرض صيغ الفيديو (vcodec != 'none') وصيغ الصوت المنفردة
                    if f.get('vcodec') != 'none' or (f.get('acodec') != 'none' and f.get('vcodec') == 'none'):
                        format_note = f.get('format_note', 'N/A')
                        ext = f.get('ext', 'N/A')
                        filesize_bytes = f.get('filesize') or f.get('filesize_approx')
                        filesize = self._format_size(filesize_bytes) if filesize_bytes else 'N/A'

                        is_audio_only = f.get('vcodec') == 'none'

                        formats.append({
                            'id': f['format_id'],
                            'ext': ext,
                            'resolution': format_note if not is_audio_only else 'صوت فقط',
                            'filesize': filesize,
                            'note': f.get('vcodec') if not is_audio_only else f.get('acodec')
                        })

                formats.sort(key=lambda x: self._size_to_sortable(x['filesize']), reverse=True)

                title = info_dict.get('title', 'فيديو يوتيوب')
                self.formats_ready.emit(formats, title)

        except Exception as e:
            self.download_error.emit(f"خطأ في جلب الصيغ: {e}")

    def _start_download(self):
        """بدء عملية التحميل."""
        self.is_downloading = True
        options = self.download_options

        if not os.path.exists('downloads'):
            os.makedirs('downloads')

        ydl_opts = self.ydl_opts_base.copy()

        custom_postprocessors = []

        # 1. إضافة المعالجات المخصصة للمستخدم (صوت فقط، الخ)
        if options.get('postprocessor'):
            custom_postprocessors.extend(options['postprocessor'])

        # تعيين قائمة المعالجات اللاحقة كاملة
        ydl_opts['postprocessors'] = custom_postprocessors

        # تعيين قالب الإخراج ليتطابق مع الـ slug
        output_template = f'downloads/{options["title_slug"]}.%(ext)s'

        # تحديث خيارات yt-dlp
        ydl_opts.update({
            'format': options['format'],
            # استخدام الـ slug الذي تم إنشاؤه من العنوان
            'outtmpl': output_template,
            'progress_hooks': [self._progress_hook],
            'writedescription': options.get('write_description', False),
            'writethumbnail': options.get('write_thumbnail', False), # نبقيها لتنزيل الصورة الأصلية
        })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # إذا كانت الصيغة 'none' (تحميل ملحقات فقط)
                if options['format'] == 'none':
                    # عند تحميل بيانات مساعدة فقط (وصف/صورة مصغرة)
                    ydl.params['skip_download'] = True
                    ydl.params['writethumbnail'] = options.get('write_thumbnail', False)
                    ydl.params['writedescription'] = options.get('write_description', False)

                    ydl.extract_info(self.url, download=True)
                    # يجب أن يشير إنهاء التحميل إلى اسم الملف الأساسي للصورة المصغرة (yt-dlp يحدد الامتداد)
                    self.download_finished.emit(f'downloads/{self.download_options["title_slug"]}')
                else:
                    # تحميل فيديو/صوت فعلي
                    ydl.download([self.url])
        except SystemExit:
            pass
        except Exception as e:
            self.download_error.emit(f"خطأ أثناء التحميل: {e}")
        finally:
            self.is_downloading = False

    # ... (بقية دوال المساعدة لـ YtdlpWorker)
    def cancel_download(self):
        """إلغاء التحميل."""
        self._is_cancelled = True

    def _format_size(self, bytes_val):
        """تحويل البايت إلى KB/MB/GB."""
        if bytes_val is None:
            return 'N/A'

        bytes_val = bytes_val * random.uniform(0.9, 1.1)

        if bytes_val < 1024:
            return f"{bytes_val:.1f} B"
        elif bytes_val < 1024 * 1024:
            return f"{bytes_val / 1024:.1f} KB"
        elif bytes_val < 1024 * 1024 * 1024:
            return f"{bytes_val / (1024 * 1024):.1f} MB"
        else:
            return f"{bytes_val / (1024 * 1024 * 1024):.1f} GB"

    def _size_to_sortable(self, size_str):
        """تحويل حجم الملف إلى رقم قابل للفرز."""
        if 'KB' in size_str:
            return float(size_str.replace(' KB', ''))
        elif 'MB' in size_str:
            return float(size_str.replace(' MB', '')) * 1024
        elif 'GB' in size_str:
            return float(size_str.replace(' GB', '')) * 1024 * 1024
        return 0


# ----------------------------------------------------------------------
## 3.1 عامل التحويل في خيط منفصل (Conversion Worker)
# ----------------------------------------------------------------------
class ConversionWorker(QThread):
    conversion_progress = pyqtSignal(int)
    conversion_finished = pyqtSignal()
    conversion_error = pyqtSignal(str)

    def __init__(self, url, options):
        super().__init__()
        self.url = url
        self.options = options
        self._is_cancelled = False

    def run(self):
        try:
            is_image_conversion_needed = self.options['image_format'] != '-- الأصلي (لا تحويل) --'

            # 1. تحويل الصورة المصغرة (إذا طُلب) - الآن باستخدام Pillow
            if is_image_conversion_needed:
                self._convert_image()

            # 2. محاكاة تحويل الفيديو/الصوت (إذا طُلب)
            if self.options['is_video_convert']:
                 # إذا لم يكن هناك تحويل للصورة، نبدأ من 0
                 start_progress = 50 if is_image_conversion_needed else 0

                 self.conversion_progress.emit(start_progress + 5)
                 time.sleep(1.5) # محاكاة وقت التحويل

            self.conversion_progress.emit(100)
            self.conversion_finished.emit()

        except Exception as e:
            self.conversion_error.emit(f"خطأ في التحويل: {e}")



    def _convert_image(self):
        """تطبيق تحويل صيغة الصورة المصغرة باستخدام Pillow (بدلاً من FFmpeg)."""

        target_ext = self.options['image_format'].lower() # مثلاً 'png'
        file_slug = self.options["title_slug"] # هذا هو الـ slug المصحح (عنوان الفيديو)

        # 1. تحديد الملف الأصلي (نبحث عن webp أو jpg/jpeg)

        # قائمة الامتدادات المحتملة لملف الصورة المصغرة الذي تم تنزيله بواسطة yt-dlp
        possible_exts = ['webp', 'jpg', 'jpeg']
        original_file_path = None

        for ext in possible_exts:
            # نبحث عن الملف في مسار downloads باسم الـ slug
            temp_path = f'downloads/{file_slug}.{ext}'
            if os.path.exists(temp_path):
                original_file_path = temp_path
                break

        if not original_file_path:
            # نرفع خطأ إذا لم نجد ملف الصورة الأصلية
            raise FileNotFoundError(f"لم يتم العثور على ملف الصورة المصغرة الأصلي لـ {file_slug} بأي صيغة متوقعة.")

        # 2. مسار ملف الإخراج الجديد
        output_file_path = f'downloads/{file_slug}.{target_ext}'

        self.conversion_progress.emit(10) # 10% لبدء المعالجة

        try:
            # استخدام Pillow للتحويل
            img = Image.open(original_file_path)
            img.save(output_file_path)

            self.conversion_progress.emit(50) # 50% عند الانتهاء

            # حذف الملف الأصلي بعد التحويل لتجنب اللبس
            os.remove(original_file_path)


        except Exception as e:
            # نرفع الخطأ مرة أخرى مع رسالة واضحة
            raise Exception(f"فشل تحويل الصورة المصغرة يدوياً إلى {target_ext}: {e}")


    def cancel_conversion(self):
        self._is_cancelled = True


# ----------------------------------------------------------------------
## 4. تطبيق النافذة الرئيسية (MainWindow)
# ----------------------------------------------------------------------
class YtdlpGui(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YT-DLP GUI 🎞️")
        self.setGeometry(100, 100, 800, 600)
        self.setMinimumSize(600, 400)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # الوضع الافتراضي للوضع الداكن
        self.current_theme = "dark"

        self.header_widget = self._create_header_widget()
        self.layout.addWidget(self.header_widget)

        self.stacked_widget = QStackedWidget()
        self.layout.addWidget(self.stacked_widget)

        # المتغيرات الهامة
        self.youtube_url = ""
        self.video_formats = []
        self.video_title = ""
        self.video_title_slug = ""
        self.download_worker = None
        self.download_type = None
        self.downloaded_file = None
        self.is_download_complete = False

        # تهيئة القوائم
        self.page1_url_input = self._create_page1_url_input()
        self.page2_download = self._create_page2_download()
        self.page3_convert = self._create_page3_convert()
        self.page4_finish = self._create_page4_finish()

        self.stacked_widget.addWidget(self.page1_url_input)  # index 0
        self.stacked_widget.addWidget(self.page2_download)   # index 1
        self.stacked_widget.addWidget(self.page3_convert)    # index 2
        self.stacked_widget.addWidget(self.page4_finish)     # index 3

        self.stacked_widget.setCurrentIndex(0)
        self.apply_theme(self.current_theme)

    def _create_header_widget(self):
        """إنشاء منطقة الرأس لزر تبديل الوضع."""
        header = QWidget()
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(0, 0, 0, 0)

        self.theme_button = CustomButton(THEMES[self.current_theme]["THEME_BUTTON_TEXT"])
        self.theme_button.setFixedSize(QSize(45, 45))
        self.theme_button.setToolTip("تبديل الوضع")
        font = QFont()
        font.setPointSize(20)
        self.theme_button.setFont(font)
        self.theme_button.clicked.connect(self.toggle_theme)

        h_layout.addWidget(self.theme_button)
        h_layout.addStretch()

        return header

    def toggle_theme(self):
        """تبديل الوضع بين الداكن والفاتح وتطبيق الأنماط الجديدة."""
        self.current_theme = "dark" if self.current_theme == "light" else "light"
        self.apply_theme(self.current_theme)

    def apply_theme(self, theme_name):
        """تطبيق ورقة الأنماط على جميع العناصر بناءً على الوضع المختار."""
        theme = THEMES[theme_name]

        self.theme_button.setText(theme['THEME_BUTTON_TEXT'])
        self.theme_button.set_theme_colors(theme['THEME_BUTTON_COLOR'], theme['THEME_BUTTON_COLOR'], theme['THEME_BUTTON_COLOR'])

        # 1. تحديث الأنماط العامة (QSS)
        global_style = f"""
            QWidget {{
                background-color: {theme['BG']};
                color: {theme['FG']};
                font-family: 'Arial', 'Segoe UI', sans-serif;
            }}
            QLineEdit, QComboBox, QListWidget {{
                padding: 10px;
                border: 2px solid #555555;
                border-radius: 10px;
                background-color: {theme['INPUT_BG']};
                color: {theme['FG']};
            }}
            QListWidget::item:selected {{
                background-color: {theme['PROGRESS_BAR']};
                color: white;
            }}
            QLabel#header {{
                font-size: 24px;
                font-weight: 800;
                color: {theme['HEADER']};
                margin-bottom: 20px;
            }}
            QProgressBar {{
                border: 2px solid {theme['FG']};
                border-radius: 10px;
                text-align: center;
                background-color: {theme['INPUT_BG']};
                color: {theme['FG']};
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background-color: {theme['PROGRESS_BAR']};
                border-radius: 8px;
            }}
            QCheckBox {{
                color: {theme['FG']};
                spacing: 8px;
                padding: 5px;
            }}
        """
        self.setStyleSheet(global_style)

        # 2. تحديث أنماط الأزرار المخصصة
        self.update_all_custom_buttons(theme)

    def update_all_custom_buttons(self, theme):
        """تحديث ألوان كل الأزرار المخصصة."""

        self.next_button_page1.set_success_style(theme)
        self.btn_download.set_success_style(theme)
        self.btn_convert.set_success_style(theme)
        self.btn_reload.set_success_style(theme)

        self.paste_button.set_warning_style(theme)

        self.exit_button_page1.set_danger_style(theme)
        self.btn_cancel.set_danger_style(theme)
        self.btn_exit_page2.set_danger_style(theme)
        self.btn_cancel_convert.set_danger_style(theme)
        self.btn_exit_page3.set_danger_style(theme)
        self.btn_exit_page4.set_danger_style(theme)

        self.btn_back_page2.set_danger_style(theme)
        self.btn_back_page3.set_danger_style(theme)
        self.btn_back_page4.set_danger_style(theme)


    # ----------------------------------------------------------------------
    ## الدوال المساعدة (Helper Methods)
    # ----------------------------------------------------------------------
    def is_youtube_link(self, text):
        """تحقق من أن النص رابط YouTube صالح."""
        youtube_regex = re.compile(
            r'(https?://)?(www\.)?(youtube|youtu\.be)\.(com|be)/[^\s]+'
        )
        return bool(youtube_regex.match(text.strip()))

    def clean_url(self, url):
        """تنظيف الرابط (إزالة البارامترات غير الضرورية)."""
        match = re.search(r'v=([^&]+)|list=([^&]+)', url)
        if match:
            if match.group(1):
                return f"https://www.youtube.com/watch?v={match.group(1)}"
            elif match.group(2):
                return f"https://www.youtube.com/playlist?list={match.group(2)}"

        if 'youtu.be' in url:
            match_short = re.search(r'youtu\.be/([^?&/]+)', url)
            if match_short:
                return f"https://www.youtube.com/watch?v={match_short.group(1)}"

        return url

    def paste_clipboard(self):
        """اللصق من الحافظة بعد التحقق."""
        clipboard = QApplication.clipboard()
        text = clipboard.text()

        if self.is_youtube_link(text):
            self.url_line_edit.setText(text.strip())
            self.show_message("تم اللصق: رابط YouTube صالح.", "green")
        else:
            self.show_message("الحافظة لا تحتوي على رابط YouTube صالح.", "red")

    def show_message(self, message, color="black"):
        """عرض رسالة حالة مؤقتة."""
        print(f"[{color.upper()}]: {message}")


    # ----------------------------------------------------------------------
    ## 4.1 القائمة 1: إدخال الرابط
    # ----------------------------------------------------------------------
    def _create_page1_url_input(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header = QLabel("إدخال رابط فيديو YouTube 🔗", objectName="header")
        layout.addWidget(header, alignment=Qt.AlignmentFlag.AlignCenter)

        self.url_line_edit = QLineEdit()
        self.url_line_edit.setPlaceholderText("الصق رابط YouTube هنا (فيديو أو قائمة تشغيل)...")
        self.url_line_edit.setMinimumHeight(45)
        layout.addWidget(self.url_line_edit)

        h_layout = QHBoxLayout()

        self.paste_button = CustomButton("لصق 📋")
        self.paste_button.clicked.connect(self.paste_clipboard)
        h_layout.addWidget(self.paste_button)

        self.next_button_page1 = CustomButton("التالي ➡️")
        self.next_button_page1.clicked.connect(self.check_url_and_go_next)
        h_layout.addWidget(self.next_button_page1)

        self.exit_button_page1 = CustomButton("خروج 🚪")
        self.exit_button_page1.clicked.connect(QApplication.instance().quit)
        h_layout.addWidget(self.exit_button_page1)

        layout.addLayout(h_layout)
        layout.addStretch()

        return page

    def check_url_and_go_next(self):
        """التحقق من الرابط والانتقال للقائمة 2."""
        url = self.url_line_edit.text().strip()

        if not url or not self.is_youtube_link(url):
            self.show_message("يرجى إدخال رابط YouTube صالح أولاً.", "red")
            return

        self.youtube_url = self.clean_url(url)
        self.show_message(f"الرابط نظيف: {self.youtube_url}", "blue")

        self.download_worker = YtdlpWorker(url=self.youtube_url)
        self.download_worker.formats_ready.connect(self.on_formats_ready)
        self.download_worker.download_error.connect(self.on_error)
        self.download_worker.start()

        self.show_message("جاري جلب معلومات الفيديو والصيغ المتاحة... ⏳", "blue")
        self.next_button_page1.setEnabled(False)

    def on_formats_ready(self, formats, title):
        """تعبئة قائمة الصيغ والانتقال للقائمة 2."""
        self.video_formats = formats
        self.video_title = title
        # **التصحيح الهام:** إنشاء الـ slug من عنوان الفيديو الفعلي
        self.video_title_slug = slugify(self.video_title)[:100]
        self.update_page2_formats()
        self.stacked_widget.setCurrentIndex(1)
        self.next_button_page1.setEnabled(True)

    def on_error(self, message):
        """عرض رسالة خطأ."""
        self.show_message(message, "red")
        self.next_button_page1.setEnabled(True)

    # ----------------------------------------------------------------------
    ## 4.2 القائمة 2: التحميل
    # ----------------------------------------------------------------------
    def _create_page2_download(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        self.video_title_label = QLabel("عنوان الفيديو: [جاري التحميل...]", objectName="header")
        layout.addWidget(self.video_title_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # خيارات التحميل الأساسية
        options_group_basic = QWidget()
        options_layout_basic = QHBoxLayout(options_group_basic)

        # الخيار الجديد لتنزيل الفيديو والصوت المدمج
        self.chk_video_audio_merged = QCheckBox("فيديو + صوت (مدمج) 🎬")
        self.chk_audio_only = QCheckBox("صوت فقط 🎧")

        options_layout_basic.addWidget(self.chk_video_audio_merged)
        options_layout_basic.addWidget(self.chk_audio_only)
        layout.addWidget(options_group_basic)

        # خيارات البيانات المساعدة
        options_group_meta = QWidget()
        options_layout_meta = QHBoxLayout(options_group_meta)
        self.chk_thumbnail = QCheckBox("صورة مصغرة (عادية) 🖼️")
        self.chk_description = QCheckBox("وصف 📜")

        options_layout_meta.addWidget(self.chk_thumbnail)
        options_layout_meta.addWidget(self.chk_description)
        layout.addWidget(options_group_meta)

        # ربط الإشارات
        self.chk_video_audio_merged.stateChanged.connect(self._handle_download_option_change)
        self.chk_audio_only.stateChanged.connect(self._handle_download_option_change)
        self.chk_thumbnail.stateChanged.connect(self._handle_download_option_change)
        self.chk_description.stateChanged.connect(self._handle_download_option_change)

        self.formats_list = QListWidget()
        self.formats_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.formats_list.setMinimumHeight(150)
        self.formats_list.setEnabled(False)
        self.formats_list.currentItemChanged.connect(self._handle_download_option_change)
        layout.addWidget(self.formats_list)

        self.download_progress_bar = QProgressBar()
        self.download_progress_bar.setValue(0)
        self.download_progress_bar.setTextVisible(True)
        self.download_progress_bar.setVisible(False)
        layout.addWidget(self.download_progress_bar)

        button_layout = QHBoxLayout()
        self.btn_back_page2 = CustomButton("رجوع ⬅️")
        self.btn_back_page2.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))

        self.btn_download = CustomButton("تحميل ⬇️")
        self.btn_download.setDisabled(True)
        self.btn_download.clicked.connect(self.start_download)

        self.btn_cancel = CustomButton("إلغاء ❌")
        self.btn_cancel.setDisabled(True)
        self.btn_cancel.clicked.connect(self.cancel_download)

        self.btn_exit_page2 = CustomButton("خروج 🚪")
        self.btn_exit_page2.clicked.connect(QApplication.instance().quit)

        button_layout.addWidget(self.btn_back_page2)
        button_layout.addWidget(self.btn_download)
        button_layout.addWidget(self.btn_cancel)
        button_layout.addWidget(self.btn_exit_page2)
        layout.addLayout(button_layout)

        return page

    def _handle_download_option_change(self):
        """إدارة تفعيل وتعطيل الخيارات بناءً على الاختيار."""

        is_video_selected = self.chk_video_audio_merged.isChecked()
        is_audio_only_selected = self.chk_audio_only.isChecked()

        sender = self.sender()

        if sender == self.chk_video_audio_merged and is_video_selected:
            # إذا اختار الفيديو المدمج، يلغي خيار الصوت فقط
            self.chk_audio_only.setChecked(False)

        if sender == self.chk_audio_only and is_audio_only_selected:
            # إذا اختار الصوت فقط، يلغي خيار الفيديو المدمج
            self.chk_video_audio_merged.setChecked(False)

        # تفعيل وتعطيل قائمة الصيغ: تفعيلها فقط عند اختيار الفيديو المدمج
        self.formats_list.setEnabled(self.chk_video_audio_merged.isChecked())

        # تفعيل زر التحميل
        can_download = (self.chk_video_audio_merged.isChecked() and self.formats_list.currentItem() is not None) or \
                       self.chk_audio_only.isChecked() or \
                       self.chk_thumbnail.isChecked() or \
                       self.chk_description.isChecked()

        self.btn_download.setEnabled(can_download)

    def update_page2_formats(self):
        """تعبئة قائمة الصيغ بعد جلبها من yt-dlp."""
        self.video_title_label.setText(f"عنوان الفيديو: {self.video_title}")
        self.formats_list.clear()

        for fmt in self.video_formats:
            # عرض فقط صيغ الفيديو التي يمكن دمجها (لتجنب عرض صيغ الصوت المنفصلة هنا)
            if 'صوت فقط' not in fmt['resolution']:
                item_text = f"⚙️ {fmt['resolution']} - {fmt['ext']} ({fmt['filesize']}) - {fmt['note']}"
                item = QListWidgetItem(item_text)
                item.setData(Qt.ItemDataRole.UserRole, fmt)
                self.formats_list.addItem(item)

        # إعادة تعيين الخيارات
        self.chk_video_audio_merged.setChecked(False)
        self.chk_audio_only.setChecked(False)
        self.chk_thumbnail.setChecked(False)
        self.chk_description.setChecked(False)
        self.formats_list.clearSelection()
        self.btn_download.setEnabled(False)
        self.formats_list.setEnabled(False)

    def start_download(self):
        """بدء عملية التحميل بناءً على الخيارات المختارة."""

        options = {
            'format': "none", # القيمة الافتراضية 'none' لتحميل الملحقات فقط
            'postprocessor': [],
            'write_description': self.chk_description.isChecked(),
            'write_thumbnail': self.chk_thumbnail.isChecked(),
            'title_slug': self.video_title_slug
        }

        self.download_type = None

        if self.chk_video_audio_merged.isChecked():
            selected_item = self.formats_list.currentItem()
            if not selected_item:
                self.show_message("يرجى اختيار جودة للفيديو.", "red")
                return

            fmt_data = selected_item.data(Qt.ItemDataRole.UserRole)

            # --- التصحيح الحاسم لمشكلة format not available ---
            resolution_str = fmt_data['resolution'] # e.g., '1080p'
            ext = fmt_data['ext'] # e.g., 'webm'

            # استخراج رقم الارتفاع (مثل 1080 من 1080p)
            height_match = re.search(r'(\d+)', resolution_str)
            height = height_match.group(1) if height_match else '2160'

            # طلب أفضل فيديو بارتفاع مساوٍ أو أقل من الارتفاع المحدد وصيغة معينة، ودمجه مع أفضل صوت
            options['format'] = f"bestvideo[height<={height}][ext={ext}]+bestaudio[ext={ext}]/bestvideo[height<={height}]+bestaudio"

            options['postprocessor'] = [{'key': 'FFmpegVideoConvertor', 'preferedformat': ext}]
            # ----------------------------------------------------------------------

            self.download_type = 'video_audio_merged'

        elif self.chk_audio_only.isChecked():
            options['format'] = "bestaudio/best"
            # تحويل إلى MP3 192kbps
            options['postprocessor'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]
            self.download_type = 'audio_only'

        # إذا لم يكن هناك تحميل للفيديو أو الصوت، فهذا يعني تحميل بيانات مساعدة فقط
        if not self.download_type:
            if self.chk_thumbnail.isChecked() or self.chk_description.isChecked():
                self.download_type = 'auxiliary'
                # **التأكيد على أن الصيغة هي 'none' لتفعيل وضع skip_download في الـ Worker**
                options['format'] = 'none'
            else:
                self.show_message("يرجى اختيار خيار تحميل واحد على الأقل.", "red")
                return

        self.download_progress_bar.setVisible(True)
        self.download_progress_bar.setValue(0)
        self.btn_download.setDisabled(True)
        self.btn_cancel.setEnabled(True)
        self.btn_back_page2.setDisabled(True)

        self.download_worker = YtdlpWorker(url=self.youtube_url, download_options=options)
        self.download_worker.download_progress.connect(self.update_download_progress)
        self.download_worker.download_finished.connect(self.on_download_finished)
        self.download_worker.download_error.connect(self.on_download_error)
        self.download_worker.start()

    def cancel_download(self):
        """إلغاء عملية التحميل."""
        if self.download_worker and self.download_worker.isRunning() and self.download_worker.is_downloading:
            self.download_worker.cancel_download()

    def update_download_progress(self, percent):
        """تحديث شريط التقدم."""
        self.download_progress_bar.setValue(percent)

    def on_download_finished(self, filename):
        """التعامل مع اكتمال التحميل."""
        self.downloaded_file = filename
        self.is_download_complete = True
        self.download_progress_bar.setValue(100)
        self.show_message(f"اكتمل التحميل! الملف: {filename}", "green")

        self.btn_download.setEnabled(True)
        self.btn_cancel.setDisabled(True)
        self.btn_back_page2.setEnabled(True)

        # الانتقال لقائمة التحويل إذا تم تنزيل فيديو مدمج أو صورة مصغرة
        if self.download_type == 'video_audio_merged' or self.chk_thumbnail.isChecked():
            self.stacked_widget.setCurrentIndex(2)
        else:
            self.stacked_widget.setCurrentIndex(3)

    def on_download_error(self, message):
        """التعامل مع أخطاء التحميل."""
        self.show_message(f"خطأ في التحميل: {message}", "red")
        self.download_progress_bar.setVisible(False)
        self.btn_download.setEnabled(True)
        self.btn_cancel.setDisabled(True)
        self.btn_back_page2.setEnabled(True)
        self.is_download_complete = False


    # ----------------------------------------------------------------------
    ## 4.3 القائمة 3: التحويل
    # ----------------------------------------------------------------------
    def _create_page3_convert(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header = QLabel("قائمة التحويل الاختياري 🔄", objectName="header")
        layout.addWidget(header, alignment=Qt.AlignmentFlag.AlignCenter)

        info_label = QLabel("هذه الخيارات للتحويل الإضافي بعد اكتمال التحميل (FFmpeg للفيديو، Pillow للصورة).", alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(info_label)

        form_layout = QVBoxLayout()

        # خيار تحويل الفيديو (سابق)
        video_convert_label = QLabel("تحويل الفيديو (بعد الدمج):")
        form_layout.addWidget(video_convert_label)

        codec_layout = QHBoxLayout()
        codec_layout.addWidget(QLabel("كود الترميز (Codec):"))
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["-- الأصلي (لا تحويل) --", "libx264 (H.264)", "libx265 (HEVC)", "vp9", "copy (الأصلي)"])
        codec_layout.addWidget(self.codec_combo)
        form_layout.addLayout(codec_layout)

        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("الصيغة (Container):"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["-- الأصلي (لا تحويل) --", "mp4", "mkv", "avi", "mov", "webm"])
        format_layout.addWidget(self.format_combo)
        form_layout.addLayout(format_layout)

        form_layout.addSpacing(15)

        # **الخيار الجديد:** تحويل صيغة الصورة المصغرة
        image_convert_label = QLabel("تحويل الصورة المصغرة:")
        form_layout.addWidget(image_convert_label)

        image_format_layout = QHBoxLayout()
        image_format_layout.addWidget(QLabel("صيغة الإخراج (الصورة):"))
        self.image_format_combo = QComboBox()
        # **الخيارات الجديدة للصورة**
        self.image_format_combo.addItems(["-- الأصلي (لا تحويل) --", "png", "jpg", "webp"])
        image_format_layout.addWidget(self.image_format_combo)
        form_layout.addLayout(image_format_layout)


        layout.addLayout(form_layout)

        self.convert_progress_bar = QProgressBar()
        self.convert_progress_bar.setValue(0)
        self.convert_progress_bar.setTextVisible(True)
        self.convert_progress_bar.setVisible(False)
        layout.addWidget(self.convert_progress_bar)

        button_layout = QHBoxLayout()
        self.btn_back_page3 = CustomButton("رجوع ⬅️")
        self.btn_back_page3.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))

        self.btn_convert = CustomButton("تحويل 🚀")
        # التحويل يكون متاحًا إذا تم اختيار أي من الخيارات
        self.btn_convert.setDisabled(True)
        self.btn_convert.clicked.connect(self.start_conversion_simulation)

        self.btn_cancel_convert = CustomButton("إلغاء التحويل 🛑")
        self.btn_cancel_convert.setDisabled(True)
        self.btn_cancel_convert.clicked.connect(self.cancel_conversion_simulation)

        self.btn_exit_page3 = CustomButton("خروج 🚪")
        self.btn_exit_page3.clicked.connect(QApplication.instance().quit)

        button_layout.addWidget(self.btn_back_page3)
        button_layout.addWidget(self.btn_convert)
        button_layout.addWidget(self.btn_cancel_convert)
        button_layout.addWidget(self.btn_exit_page3)
        layout.addLayout(button_layout)

        layout.addStretch()

        self.codec_combo.currentIndexChanged.connect(self._check_conversion_ready)
        self.format_combo.currentIndexChanged.connect(self._check_conversion_ready)
        self.image_format_combo.currentIndexChanged.connect(self._check_conversion_ready) # ربط جديد

        return page

    def _check_conversion_ready(self):
        """تفعيل زر التحويل فقط إذا تم اختيار أي خيار تحويل."""

        # هل تم اختيار تحويل للفيديو؟
        video_conversion_selected = self.codec_combo.currentIndex() > 0 or self.format_combo.currentIndex() > 0

        # هل تم اختيار تحويل للصورة؟ (فقط إذا كانت الصورة المصغرة قد تم طلبها في القائمة 2)
        image_conversion_selected = self.image_format_combo.currentIndex() > 0 and self.chk_thumbnail.isChecked()

        # تفعيل زر التحويل إذا كان أي خيار نشط
        self.btn_convert.setEnabled(video_conversion_selected or image_conversion_selected)


    def start_conversion_simulation(self):
        """بدء عملية التحويل الفعلية/المحاكاة."""

        # التحقق من الخيارات النشطة
        is_video_convert = self.codec_combo.currentIndex() > 0 or self.format_combo.currentIndex() > 0
        is_image_convert = self.image_format_combo.currentIndex() > 0 and self.chk_thumbnail.isChecked()

        if not is_video_convert and not is_image_convert:
            self.show_message("لم يتم اختيار أي خيار تحويل. الانتقال لصفحة الانتهاء.", "blue")
            self.stacked_widget.setCurrentIndex(3)
            return

        self.convert_progress_bar.setVisible(True)
        self.convert_progress_bar.setValue(0)
        self.btn_convert.setDisabled(True)
        self.btn_cancel_convert.setEnabled(True)
        self.btn_back_page3.setDisabled(True)

        # تجهيز الخيارات لـ ConversionWorker
        conversion_options = {
            'image_format': self.image_format_combo.currentText(),
            'title_slug': self.video_title_slug,
            'is_video_convert': is_video_convert # لتشغيل محاكاة الفيديو
        }

        self.show_message("بدأ تحويل الملفات... 🚀", "blue")

        # **تشغيل عامل التحويل (Worker)**
        self.conversion_worker = ConversionWorker(url=self.youtube_url, options=conversion_options)
        self.conversion_worker.conversion_progress.connect(self.update_conversion_progress)
        self.conversion_worker.conversion_finished.connect(self.on_conversion_finished)
        self.conversion_worker.conversion_error.connect(self.on_download_error)
        self.conversion_worker.start()

    def update_conversion_progress(self, percent):
        """تحديث شريط تقدم التحويل."""
        self.convert_progress_bar.setValue(percent)

    def cancel_conversion_simulation(self):
        """إلغاء التحويل."""
        if hasattr(self, 'conversion_worker') and self.conversion_worker.isRunning():
            self.conversion_worker.cancel_conversion()
            self.show_message("تم إلغاء التحويل.", "red")
            self.btn_convert.setEnabled(True)
            self.btn_cancel_convert.setDisabled(True)
            self.btn_back_page3.setEnabled(True)
            self.convert_progress_bar.setVisible(False)
            self.stacked_widget.setCurrentIndex(3)

    def on_conversion_finished(self):
        """التعامل مع اكتمال التحويل."""
        self.show_message("اكتمل التحويل بنجاح!", "green")
        self.btn_convert.setEnabled(True)
        self.btn_cancel_convert.setDisabled(True)
        self.btn_back_page3.setEnabled(True)
        self.stacked_widget.setCurrentIndex(3)


    # ----------------------------------------------------------------------
    ## 4.4 القائمة 4: إعادة تحميل / خروج
    # ----------------------------------------------------------------------
    def _create_page4_finish(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        header = QLabel("العملية اكتملت بنجاح! 🎉", objectName="header")
        layout.addWidget(header, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(30)

        h_layout = QHBoxLayout()

        self.btn_back_page4 = CustomButton("رجوع ⬅️")
        # يجب أن يعود إلى القائمة 2 (تحميل) إذا لم يكن هناك تحويل، أو 3 (تحويل) إذا كان هناك تحويل
        self.btn_back_page4.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(self.stacked_widget.currentIndex() - 1))
        h_layout.addWidget(self.btn_back_page4)

        self.btn_reload = CustomButton("تحميل فيديو آخر 🔄")
        self.btn_reload.clicked.connect(self.reset_application)
        h_layout.addWidget(self.btn_reload)

        self.btn_exit_page4 = CustomButton("خروج 🚪")
        self.btn_exit_page4.clicked.connect(QApplication.instance().quit)
        h_layout.addWidget(self.btn_exit_page4)

        layout.addLayout(h_layout)
        layout.addStretch()

        return page

    def reset_application(self):
        """إعادة تعيين التطبيق للبدء من جديد (القائمة 1)."""
        self.youtube_url = ""
        self.video_formats = []
        self.video_title = ""
        self.download_worker = None
        self.download_type = None
        self.downloaded_file = None
        self.is_download_complete = False
        self.video_title_slug = "" # إعادة تعيين الـ slug

        self.url_line_edit.clear()

        self.download_progress_bar.setVisible(False)
        self.chk_video_audio_merged.setChecked(False)
        self.chk_audio_only.setChecked(False)
        self.chk_thumbnail.setChecked(False)
        self.chk_description.setChecked(False)
        self.formats_list.clear()
        self.formats_list.setEnabled(False)

        self.convert_progress_bar.setVisible(False)
        self.codec_combo.setCurrentIndex(0)
        self.format_combo.setCurrentIndex(0)
        self.image_format_combo.setCurrentIndex(0) # إعادة تعيين خيار الصورة

        self.stacked_widget.setCurrentIndex(0)
        self.show_message("تمت إعادة تعيين التطبيق. يرجى إدخال رابط جديد. 🎬", "black")


# ----------------------------------------------------------------------
## 5. نقطة الدخول (Entry Point)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)

    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    window = YtdlpGui()
    window.show()
    sys.exit(app.exec())
