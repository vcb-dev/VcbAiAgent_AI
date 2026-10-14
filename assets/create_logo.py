#!/usr/bin/env python3
"""
Tạo logo HuyK - Viễn Chí Bảo chuẩn nhận diện (PNG có kênh Alpha trong suốt)
"""
from PIL import Image, ImageDraw, ImageFont
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent   # VCB_AI/assets


def create_huyk_logo(output_path):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    width, height = 700, 160
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Nền bo góc nhẹ bán trong suốt tối màu để hiển thị rõ trên mọi cảnh video
    bg_box = [10, 10, width - 10, height - 10]
    draw.rounded_rectangle(bg_box, radius=24, fill=(15, 18, 24, 210), outline=(212, 175, 55, 230), width=3)

    # Vẽ biểu tượng viên kim cương / hoa thị ngôi sao vàng (Gold #D4AF37)
    center_icon_x = 75
    center_icon_y = height // 2
    # Vẽ sao 8 cánh / diamond star
    star_color = (245, 215, 110, 255)
    # Thoi lớn
    draw.polygon([
        (center_icon_x, center_icon_y - 38),
        (center_icon_x + 22, center_icon_y),
        (center_icon_x, center_icon_y + 38),
        (center_icon_x - 22, center_icon_y)
    ], fill=star_color)
    # Thoi nhỏ chéo
    draw.polygon([
        (center_icon_x - 20, center_icon_y - 20),
        (center_icon_x + 20, center_icon_y - 20),
        (center_icon_x + 20, center_icon_y + 20),
        (center_icon_x - 20, center_icon_y + 20)
    ], fill=(212, 175, 55, 200))
    # Điểm sáng tâm
    draw.ellipse([center_icon_x - 8, center_icon_y - 8, center_icon_x + 8, center_icon_y + 8], fill=(255, 255, 255, 255))

    # Font chữ
    font_main = None
    font_sub = None
    try:
        font_main = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 46)
        font_sub = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 22)
    except Exception:
        font_main = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    # Chữ "HUYK - VIENCHIBAO"
    draw.text((140, 28), "HUYK - VIENCHIBAO", font=font_main, fill=(255, 255, 255, 255))
    # Dòng phụ "CHẾ TÁC KIM HOÀN THỦ CÔNG"
    draw.text((145, 92), "CHẾ TÁC KIM HOÀN THỦ CÔNG", font=font_sub, fill=(212, 175, 55, 255))

    img.save(output_path, "PNG")
    print(f"✅ Đã tạo logo thành công: {output_path}")

if __name__ == "__main__":
    create_huyk_logo(str(HERE / "logo_huyk_vienchibao.png"))
