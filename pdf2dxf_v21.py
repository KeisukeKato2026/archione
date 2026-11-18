import sys

from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QFileDialog, QLineEdit, QMessageBox
)
#from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtGui import QPainter, QPen, QColor
from PyQt5.QtCore import Qt, QPoint
from pdf2image import convert_from_path
from PyQt5.QtGui import QImage, QPixmap  # PySide6なら 'from PySide6.QtGui import ...' に読み替え
from PIL import Image

def pil_to_qimage(pil_image):
    if pil_image.mode == "RGB":
        r, g, b = pil_image.split()
        image = Image.merge("RGB", (b, g, r))
        data = image.tobytes()
        qimage = QImage(data, image.width, image.height, QImage.Format_RGB888)
        return qimage

    elif pil_image.mode == "RGBA":
        r, g, b, a = pil_image.split()
        image = Image.merge("RGBA", (b, g, r, a))
        data = image.tobytes()
        qimage = QImage(data, image.width, image.height, QImage.Format_RGBA8888)
        return qimage
    
    else:
        pil_image = pil_image.convert("RGBA")
        return pil_to_qimage(pil_image)

import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # 実際のインストール場所に合わせて修正

import cv2
import numpy as np
from math import atan2, degrees, sqrt

def extract_text_with_position(pil_image):
    # PIL画像 → OpenCV画像に変換（RGB→BGR）
    cv_img = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

    # pytesseractに指定して文字認識、位置情報も取得
    # output_type=pytesseract.Output.DICT で詳細情報を辞書で受け取る
    data = pytesseract.image_to_data(cv_img, lang='jpn', output_type=pytesseract.Output.DICT)

    texts = []
    n_boxes = len(data['level'])
    for i in range(n_boxes):
        text = data['text'][i].strip()
        if text == '':
            continue
        x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
        cx = x + w / 2
        cy = y + h / 2
        texts.append({'text': text, 'x': cx, 'y': cy, 'w': w, 'h': h})
    return texts

def merge_similar_lines(lines, angle_thresh=5, dist_thresh=300):
    def angle_of_line(line):
        dx = line[2] - line[0]
        dy = line[3] - line[1]
        return degrees(atan2(dy, dx))

    def normalized_angle(angle):
        angle = angle % 180
        return angle

    def angle_difference(a1, a2):
        diff = abs(normalized_angle(a1) - normalized_angle(a2))
        if diff > 90:
            diff = 180 - diff
        return diff

    def lines_close(l1, l2):
        # 端点距離ではなく平行線同士のx座標またはy座標の差が近いかを判定する例
        # 水平線ならy座標差、垂直線ならx座標差を主に見る
        # まず角度を見て判定
        angle1 = normalized_angle(angle_of_line(l1))
        if angle1 < angle_thresh or abs(angle1 - 180) < angle_thresh:
            # 水平線に近いとみなしy座標差をチェック
            y1 = (l1[1] + l1[3]) / 2
            y2 = (l2[1] + l2[3]) / 2
            return abs(y1 - y2) < dist_thresh
        elif abs(angle1 - 90) < angle_thresh:
            # 垂直線に近いとみなしx座標差をチェック
            x1 = (l1[0] + l1[2]) / 2
            x2 = (l2[0] + l2[2]) / 2
            return abs(x1 - x2) < dist_thresh
        else:
            # その他の斜め線の場合は簡易的に端点距離チェック
            points1 = [(l1[0], l1[1]), (l1[2], l1[3])]
            points2 = [(l2[0], l2[1]), (l2[2], l2[3])]
            for p1 in points1:
                for p2 in points2:
                    dist = sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)
                    if dist < dist_thresh:
                        return True
            return False

    merged = []
    used = [False]*len(lines)

    for i, line_i in enumerate(lines):
        if used[i]:
            continue
        angle_i = angle_of_line(line_i)
        group = [line_i]
        used[i] = True

        for j in range(i+1, len(lines)):
            if used[j]:
                continue
            angle_j = angle_of_line(lines[j])
            diff = angle_difference(angle_i, angle_j)
            if diff < angle_thresh and lines_close(line_i, lines[j]):
                group.append(lines[j])
                used[j] = True

        xs = []
        ys = []
        for ln in group:
            xs.extend([ln[0], ln[2]])
            ys.extend([ln[1], ln[3]])
        new_line = (min(xs), min(ys), max(xs), max(ys))
        merged.append(new_line)

    return merged

import cv2
import numpy as np

import ezdxf

class PDFViewer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF原点指定 - 線分・交点検出付き")

        self.pdf_path = None
        self.pil_image = None  # PIL画像を保持
        self.base_pixmap = None  # 元画像pixmap

        self.lines = []
        self.intersections = []
        self.origin_point = None
        self.origin_intersection = None
        self.scale = None

        self.label = QLabel("PDF画像を読み込んでください")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMouseTracking(True)
        self.label.mousePressEvent = self.on_mouse_click

        self.load_btn = QPushButton("PDF読み込み")
        self.load_btn.clicked.connect(self.load_pdf)

        self.scale_input = QLineEdit()
        self.scale_input.setPlaceholderText("縮尺例：100（1/100なら100）")

        self.info_label = QLabel("画像をクリックすると近傍交点が原点に設定されます")

        self.ok_btn = QPushButton("確定")
        self.ok_btn.clicked.connect(self.confirm_settings)

        vbox = QVBoxLayout()
        vbox.addWidget(self.load_btn)
        vbox.addWidget(self.label)

        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("縮尺（1/X）:"))
        hbox.addWidget(self.scale_input)
        vbox.addLayout(hbox)

        vbox.addWidget(self.info_label)
        vbox.addWidget(self.ok_btn)

        self.setLayout(vbox)

    def load_pdf(self):
        print("load_pdf")
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(self, "PDFファイルを選択", "", "PDF Files (*.pdf)", options=options)
        if not file_path:
            print("load_pdf return")
            return
        self.pdf_path = file_path

        print("lad_pdf2")

        pages = convert_from_path(self.pdf_path, dpi=300)

        print("load_pdf3")
              
        self.pil_image = pages[0]

        qimage = pil_to_qimage(self.pil_image)

        print("QImage size:", qimage.width(), qimage.height())

        MAX_WIDTH = 600
        w, h = self.pil_image.size
        print(w,h)
        if w > MAX_WIDTH:
           new_h = int(h * MAX_WIDTH / w)
           resized_image = self.pil_image.resize((MAX_WIDTH, new_h))
        else:
           resized_image = self.pil_image
        print("resized_image:",resized_image)

        # Pillow画像からQImage変換しpixmap作成
        qimage = pil_to_qimage(resized_image)
        print("QImage:", qimage.width(), qimage.height(), "isNull:", qimage.isNull())
        self.base_pixmap = QPixmap.fromImage(qimage)
        print("QPixmap created")
        print("load_pdf5")

        # OpenCV処理は Pillow 画像で行う（リサイズ済みのほうを）
        # 画像処理：線分・交点検出
        #self.lines, self.intersections = self.process_pil_image_for_lines(resized_image)
        # 円弧や円の検出
        #self.lines, self.intersections, self.circles = self.process_pil_image_for_shapes(resized_image)

        # 線分・交点検出、まとめ済みを格納
        lines1, intersections1 = self.process_pil_image_for_lines(resized_image)
        lines2, intersections2, circles = self.process_pil_image_for_shapes(resized_image)

        # process_pil_image_for_shapes内にまとめが入っているが、念のため最終的にmergeをもう一度かける例：
        self.lines = merge_similar_lines(lines2)  
        self.intersections = self.find_intersections(self.lines)
        self.circles = circles

        print(f"検出線分数（まとめ後）: {len(self.lines)}")  # ここで件数を確認

        self.texts = extract_text_with_position(resized_image)
        print("認識テキスト数:", len(self.texts))

        # 表示更新
        self.origin_point = None
        self.origin_intersection = None
        self.update_image()

    def update_image(self):
        if self.base_pixmap is None:
            print("update_image EXIT")
            return

        pixmap = self.base_pixmap.copy()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # 線を緑で描く
        pen_line = QPen(QColor(0, 255, 0, 180))
        pen_line.setWidth(2)
        painter.setPen(pen_line)
        for line in self.lines:
            painter.drawLine(line[0], line[1], line[2], line[3])

        # 交点を赤丸で描く
        pen_point = QPen(QColor(255, 0, 0))
        pen_point.setWidth(3)
        painter.setPen(pen_point)
        for pt in self.intersections:
            painter.drawEllipse(QPoint(int(pt[0]), int(pt[1])), 5, 5)
            #print("intersection:", pt[0], pt[1])

        # 原点は青丸で描く
        if self.origin_intersection:#
            pen_origin = QPen(QColor(0, 0, 255))
            pen_origin.setWidth(4)
            painter.setPen(pen_origin)
            pt = self.origin_intersection
            painter.drawEllipse(QPoint(int(pt[0]), int(pt[1])), 8, 8)

        painter.end()

        self.label.setPixmap(pixmap)
        self.label.adjustSize()

    def on_mouse_click(self, event):
        if not self.intersections:
            self.info_label.setText("交点が検出されていません。PDFを再読み込みしてください。")
            return

        x = event.pos().x()
        y = event.pos().y()
        print(x, y)

        pixmap = self.label.pixmap()
        if pixmap is None:
            self.info_label.setText("画像が読み込まれていません。")
            return

        # QLabelサイズとpixmapサイズを取得
        lbl_w = self.label.width()
        lbl_h = self.label.height()
        pix_w = pixmap.width()
        pix_h = pixmap.height()

        # QLabelに対してpixmapが中央配置なら、画像左上座標は
        offset_x = (lbl_w - pix_w) // 2
        offset_y = (lbl_h - pix_h) // 2

        # クリック座標から画像上の座標に変換
        img_x = x - offset_x
        img_y = y - offset_y

        # 画像外クリックなら無視
        if img_x < 0 or img_x >= pix_w or img_y < 0 or img_y >= pix_h:
            self.info_label.setText("画像の外側をクリックしました。")
            return

        clicked_pt = np.array([img_x, img_y])
        dists = [np.linalg.norm(clicked_pt - np.array(pt)) for pt in self.intersections]
        min_dist = min(dists)
        min_idx = dists.index(min_dist)

        # クリック位置に近い交点を探す（距離50ピクセル以内）
        #clicked_pt = np.array([x, y])
        #dists = [np.linalg.norm(clicked_pt - np.array(pt)) for pt in self.intersections]
        #print(dists)
        #min_dist = min(dists)
        #min_idx = dists.index(min_dist)
        print(min_dist)

        if min_dist < 50:
           self.origin_intersection = self.intersections[min_idx]
           self.origin_point = QPoint(int(self.origin_intersection[0]), int(self.origin_intersection[1]))
           self.info_label.setText(f"原点候補設定: ({int(self.origin_intersection[0])}, {int(self.origin_intersection[1])}), 距離: {min_dist:.1f}px")
           self.update_image()
        else:
           self.info_label.setText("近傍の交点が見つかりません。もっと正確にクリックしてください。")
  
    def confirm_settings(self):
        if self.base_pixmap is None:
            QMessageBox.warning(self, "警告", "PDF画像を先に読み込んでください。")
            return
        if self.origin_intersection is None:
            QMessageBox.warning(self, "警告", "画像上の交点から原点をクリックで指定してください。")
            return
        s = self.scale_input.text()
        if not s.isdigit() or int(s) <= 0:
            QMessageBox.warning(self, "警告", "縮尺は正の整数で入力してください。")
            return

        self.scale_denominator = int(s)
        self.scale = 1.0 / self.scale_denominator

        QMessageBox.information(self, "設定完了",
                                f"原点: ({int(self.origin_intersection[0])}, {int(self.origin_intersection[1])})\n縮尺: 1/{int(s)}")

        # ここに座標変換やDXF出力処理を追加できます

    # --- 画像処理関連関数 ---

    def process_pil_image_for_lines(self, pil_image):
        cv_img = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5,5), 0)
        edges = cv2.Canny(blurred, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=80, minLineLength=50, maxLineGap=10)
 
        if lines is None:
           return [], []

        lines_list = []

        for line in lines:
            points = line if line.ndim == 1 else line[0]
            lines_list.append(tuple(points))

        merged_lines = merge_similar_lines(lines_list)
        intersections = self.find_intersections(merged_lines)
        return merged_lines, intersections

        #intersections = self.find_intersections(lines_list)
        #return lines_list, intersections

    def find_intersections(self, lines):
        points = []
        n = len(lines)
        for i in range(n):
            for j in range(i+1, n):
                pt = self.compute_intersection(lines[i], lines[j])
                if pt is not None:
                    points.append(pt)
        return points

    def compute_intersection(self, line1, line2):
        # line1, line2 : (x1,y1,x2,y2)
        def line(p1, p2):
            A = (p1[1] - p2[1])
            B = (p2[0] - p1[0])
            C = (p1[0]*p2[1] - p2[0]*p1[1])
            return A, B, -C

        L1 = line((line1[0], line1[1]), (line1[2], line1[3]))
        L2 = line((line2[0], line2[1]), (line2[2], line2[3]))

        D = L1[0]*L2[1] - L1[1]*L2[0]
        if D == 0:
            return None  # 平行線

        x = (L1[2]*L2[1] - L1[1]*L2[2]) / D
        y = (L1[0]*L2[2] - L1[2]*L2[0]) / D

        def on_segment(p, q, r):
            return (min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and
                    min(p[1], r[1]) <= q[1] <= max(p[1], r[1]))

        p1 = (line1[0], line1[1])
        p2 = (line1[2], line1[3])
        p3 = (line2[0], line2[1])
        p4 = (line2[2], line2[3])
        pt = (x,y)

        if on_segment(p1, pt, p2) and on_segment(p3, pt, p4):
            return pt
        else:
            return None

    #円、円弧の抽出
    def process_pil_image_for_shapes(self, pil_image):
        cv_img = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # 線分検出（既存コード）
        edges = cv2.Canny(blurred, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=80, minLineLength=50, maxLineGap=10)

        lines_list = []
        if lines is not None:
            for line in lines:
                points = line if line.ndim == 1 else line[0]
                lines_list.append(tuple(points))

        # 線分をまとめる
        merged_lines = merge_similar_lines(lines_list)

        # 円検出（HoughCircles）
        circles = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT, dp=1.2, minDist=20,
                               param1=50, param2=30, minRadius=5, maxRadius=100)
        circles_list = []
        if circles is not None:
            circles = np.uint16(np.around(circles))
            for c in circles[0, :]:
                x, y, r = c
                circles_list.append((x, y, r))

        # 円弧検出は難しいのでここでは線分の集合を円弧として扱いません。（応用で部分円を検出可能）

        # 交点検出は既存関数を使う
        intersections = self.find_intersections(lines_list)
        return lines_list, intersections, circles_list

    def confirm_settings(self):
        # 既存コードの後に続けて
        if self.base_pixmap is None:
            QMessageBox.warning(self, "警告", "PDF画像を先に読み込んでください。")
            return
        if self.origin_intersection is None:
            QMessageBox.warning(self, "警告", "画像上の交点から原点をクリックで指定してください。")
            return
        s = self.scale_input.text()
        if not s.isdigit() or int(s) <= 0:
            QMessageBox.warning(self, "警告", "縮尺は正の整数で入力してください。")
            return
        self.scale_denominator = int(s)

        self.scale = 1.0 / int(s)

        # DXF作成処理呼び出し
        dxf_path = QFileDialog.getSaveFileName(self, "DXFファイルを保存", "", "DXF Files (*.dxf)")[0]
        if not dxf_path:
            return

        # 座標変換＆DXF作成
        self.create_dxf_file(dxf_path)

        QMessageBox.information(self, "完了", f"DXFファイルを保存しました:\n{dxf_path}")

    def create_dxf_file(self, filepath):
        # 画像サイズ・原点座標
        img_w = self.base_pixmap.width()
        img_h = self.base_pixmap.height()
        ox, oy = self.origin_intersection  # 原点の画像座標(px)

        PIXEL_TO_MM = 25.4 / 300.0  # dpi=300固定。読み込みdpiに合わせる

        # DXF座標系は通常右上が原点の建築図面でY増方向が上と仮定    
        # 画像は左上が(0,0)、Y増方向が下なのでY軸反転を行う
        def to_dxf_coords(x_px, y_px):
            x = (x_px - ox) * PIXEL_TO_MM / int(self.scale_denominator)  # 縮尺分割り算に注意
            y = (oy - y_px) * PIXEL_TO_MM / int(self.scale_denominator)
            return x, y
    
        doc = ezdxf.new(dxfversion='R2010')
        msp = doc.modelspace()

        # 線分を変換して追加
        for line in self.lines:
            x1, y1 = to_dxf_coords(line[0], line[1])
            x2, y2 = to_dxf_coords(line[2], line[3])
            msp.add_line((x1, y1), (x2, y2))

        # ここに円弧や文字処理を追加可能（今回は線分のみ）
        # 円追加
        for (x_c, y_c, r) in getattr(self, 'circles', []):
            cx, cy = to_dxf_coords(x_c, y_c)
            radius = r * PIXEL_TO_MM / self.scale_denominator
            msp.add_circle((cx, cy), radius)

        #文字処理
        # 文字追加

        for t in getattr(self, 'texts', []):
            tx, ty = to_dxf_coords(t['x'], t['y'])
            text_entity = msp.add_text(t['text'], dxfattribs={'height': 2.5})
            text_entity.dxf.insert = (tx, ty)
            text_entity.dxf.halign = 1  # 水平中央揃え（0=左, 1=中央, 2=右）
            # valign属性はTEXTエンティティでは使用できないため通常は使用不可

        doc.saveas(filepath)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = PDFViewer()
    viewer.resize(900, 700)
    #viewer.resize(1920, 1080)
    viewer.show()
    sys.exit(app.exec_())
