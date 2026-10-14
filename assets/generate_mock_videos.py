#!/usr/bin/env python3
"""
Tạo bộ dữ liệu Testing Mock-up gồm 3 video nguồn dài từ 2 đến 3 phút:
- video_1_che_tac_source.mp4 (Dài 150s = 2m30s)
- video_2_huyk_source.mp4 (Dài 120s = 2m00s)
- video_3_san_pham_source.mp4 (Dài 120s = 2m00s)

Mỗi video chứa nhiều phân cảnh thực tế với nhãn thời gian, thông số kỹ thuật và đồ họa nhận diện.
"""
import os
import subprocess
from PIL import Image, ImageDraw, ImageFont

def ensure_dir(d):
    os.makedirs(d, exist_ok=True)

def create_graphic_card(filepath, title, subtitle, tag_badge, color_theme, icon_type="craft"):
    """Tạo card đồ họa trực quan đại diện cho từng công đoạn"""
    w, h = 860, 520
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Khung bo góc gradient viền sáng
    card_box = [10, 10, w - 10, h - 10]
    draw.rounded_rectangle(card_box, radius=32, fill=(*color_theme, 230), outline=(245, 215, 110, 240), width=4)

    try:
        font_tag = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 26)
        font_title = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 44)
        font_sub = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
    except Exception:
        font_tag = font_title = font_sub = ImageFont.load_default()

    # Tag Badge
    badge_box = [40, 40, 40 + len(tag_badge) * 16 + 40, 85]
    draw.rounded_rectangle(badge_box, radius=12, fill=(212, 175, 55, 240))
    draw.text((55, 48), tag_badge, font=font_tag, fill=(15, 15, 15, 255))

    # Icon đồ họa đại diện
    cx, cy = w // 2, 210
    if icon_type == "flame":
        # Lửa nung kim hoàn
        draw.polygon([(cx, cy - 70), (cx + 45, cy + 40), (cx - 45, cy + 40)], fill=(255, 100, 30, 240))
        draw.polygon([(cx, cy - 40), (cx + 25, cy + 35), (cx - 25, cy + 35)], fill=(255, 220, 50, 255))
    elif icon_type == "hammer":
        # Búa & Đe rèn
        draw.rectangle([cx - 50, cy + 15, cx + 50, cy + 45], fill=(160, 170, 185, 240))
        draw.polygon([(cx - 25, cy - 60), (cx + 25, cy - 60), (cx + 15, cy + 15), (cx - 15, cy + 15)], fill=(220, 140, 60, 240))
    elif icon_type == "diamond":
        # Kim cương giác cắt lấp lánh
        draw.polygon([(cx - 60, cy - 20), (cx - 30, cy - 60), (cx + 30, cy - 60), (cx + 60, cy - 20), (cx, cy + 60)], fill=(180, 230, 255, 240), outline=(255, 255, 255, 255), width=3)
        draw.line([(cx - 30, cy - 60), (cx, cy + 60)], fill=(255, 255, 255, 200), width=2)
        draw.line([(cx + 30, cy - 60), (cx, cy + 60)], fill=(255, 255, 255, 200), width=2)
        draw.line([(cx - 60, cy - 20), (cx + 60, cy - 20)], fill=(255, 255, 255, 220), width=2)
    elif icon_type == "person":
        # HuyK chuyên gia
        draw.ellipse([cx - 45, cy - 65, cx + 45, cy + 25], fill=(230, 180, 140, 255))
        draw.polygon([(cx - 70, cy + 70), (cx + 70, cy + 70), (cx + 40, cy + 25), (cx - 40, cy + 25)], fill=(30, 45, 75, 255))
        # Tạp dề da
        draw.polygon([(cx - 30, cy + 70), (cx + 30, cy + 70), (cx + 20, cy + 35), (cx - 20, cy + 35)], fill=(160, 90, 40, 255))
    else:
        # Cưa lọng / Dụng cụ
        draw.rectangle([cx - 60, cy - 40, cx + 60, cy + 40], fill=(70, 85, 105, 240), outline=(212, 175, 55, 255), width=3)

    # Tiêu đề
    draw.text((50, 320), title, font=font_title, fill=(255, 255, 255, 255))
    # Mô tả phụ
    draw.text((50, 390), subtitle, font=font_sub, fill=(210, 225, 245, 240))
    # Gợi ý cắt ghép cho AI
    draw.text((50, 445), "⚡ Gợi ý cắt: Trích xuất 4s - 8s đoạn thao tác đắt giá nhất", font=font_tag, fill=(245, 215, 110, 240))

    img.save(filepath, "PNG")

def generate_video_1():
    """Sinh Video 1: 150 giây (2m30s) quy trình chế tác kim hoàn"""
    output_file = "mock_data/video_1_che_tac_source.mp4"
    temp_dir = "mock_data/temp_cards_v1"
    ensure_dir(temp_dir)
    print("🎬 Đang tạo Video 1 (150s - Chế tác kim hoàn)...")

    # Tạo các card cho 5 phân đoạn
    create_graphic_card(f"{temp_dir}/c1.png", "CÔNG ĐOẠN 1: NUNG CHẢY KIM LOẠI", "Khò lửa nung vàng trong chén sứ nhiệt độ 1064°C", "TAG: NUNG_CHAY_LUA", (35, 12, 6), "flame")
    create_graphic_card(f"{temp_dir}/c2.png", "CÔNG ĐOẠN 2: GÕ BÚA CÁN PHÔI", "Rèn đập phôi nhẫn trên đe thép kim hoàn gia truyền", "TAG: CAN_GO_BUA", (20, 25, 35), "hammer")
    create_graphic_card(f"{temp_dir}/c3.png", "CÔNG ĐOẠN 3: CƯA LỌNG HOA VĂN", "Lưỡi cưa chỉ 0.2mm lượn theo kinh chú Bát Nhã", "TAG: CUA_LONG_KHAC", (30, 20, 10), "craft")
    create_graphic_card(f"{temp_dir}/c4.png", "CÔNG ĐOẠN 4: VÀO CHẤU ĐÍNH KIM CƯƠNG", "Soi kính hiển vi vi mô, siết từng chấu giữ đá quý", "TAG: DINH_DA_KIM_CUONG", (10, 25, 45), "diamond")
    create_graphic_card(f"{temp_dir}/c5.png", "CÔNG ĐOẠN 5: ĐÁNH BÓNG & SIÊU ÂM", "Chổi đánh bóng gương & bồn sục rửa siêu âm khử bụi", "TAG: DANH_BONG_HOAN_THIEN", (35, 30, 10), "diamond")

    # Lệnh FFmpeg tạo video 150s hoàn chỉnh với background chuyển động và timecode
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=0x0a0c10:s=1080x1920:d=150:r=30",
        "-loop", "1", "-i", f"{temp_dir}/c1.png",
        "-loop", "1", "-i", f"{temp_dir}/c2.png",
        "-loop", "1", "-i", f"{temp_dir}/c3.png",
        "-loop", "1", "-i", f"{temp_dir}/c4.png",
        "-loop", "1", "-i", f"{temp_dir}/c5.png",
        "-filter_complex",
        "[0:v]drawbox=x=40:y=60:w=1000:h=120:color=black@0.7:t=fill,"
        "drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:text='VIDEO NGUỒN SỐ 1 - KHO TƯ LIỆU CHẾ TÁC (150s)':x=70:y=90:fontsize=36:fontcolor=white:box=0,"
        "drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:text='THỜI GIAN GỐC\\: %{pts\\:hms} / 00\\:02\\:30':x=70:y=138:fontsize=30:fontcolor=0xD4AF37,"
        "drawbox=x=40:y=1820:w=1000:h=40:color=white@0.2:t=fill,"
        "drawbox=x=40:y=1820:w='1000*t/150':h=40:color=0xD4AF37:t=fill[base];"
        "[base][1:v]overlay=x=(W-w)/2:y=650:enable='between(t,0,30)'[v1];"
        "[v1][2:v]overlay=x=(W-w)/2:y=650:enable='between(t,30,60)'[v2];"
        "[v2][3:v]overlay=x=(W-w)/2:y=650:enable='between(t,60,90)'[v3];"
        "[v3][4:v]overlay=x=(W-w)/2:y=650:enable='between(t,90,120)'[v4];"
        "[v4][5:v]overlay=x=(W-w)/2:y=650:enable='between(t,120,150)',"
        "drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:text='RAW FOOTAGE TỰ QUAY - CHƯA CẮT GHÉP':x=(w-text_w)/2:y=1750:fontsize=28:fontcolor=white@0.8[vout]",
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        output_file
    ]
    subprocess.run(cmd, check=True)
    print(f"✅ Đã tạo thành công: {output_file}")

def generate_video_2():
    """Sinh Video 2: 120 giây (2m00s) HuyK Talking Head & Giảng giải"""
    output_file = "mock_data/video_2_huyk_source.mp4"
    temp_dir = "mock_data/temp_cards_v2"
    ensure_dir(temp_dir)
    print("🎬 Đang tạo Video 2 (120s - HuyK A-Roll Talking)...")

    create_graphic_card(f"{temp_dir}/c1.png", "HUYK MỞ ĐẦU: Ý TƯỞNG ĐỘC BẢN", "Chào khán giả & đặt câu hỏi gây tò mò về chiếc nhẫn", "TAG: HUYK_INTRO", (20, 30, 45), "person")
    create_graphic_card(f"{temp_dir}/c2.png", "HUYK BÍ QUYẾT: KIỂM SOÁT LỬA", "Chia sẻ kinh nghiệm nung phôi vàng không bị rỗ", "TAG: HUYK_GIAI_THICH_LUA", (35, 25, 15), "person")
    create_graphic_card(f"{temp_dir}/c3.png", "HUYK CHIA SẺ: ĐỘ KHÓ CƯA LỌNG", "Nhấn mạnh độ chính xác từng milimet hoa văn", "TAG: HUYK_GIAI_THICH_CUA", (25, 20, 35), "person")
    create_graphic_card(f"{temp_dir}/c4.png", "HUYK KỸ THUẬT: ĐỘ KHÍT CHẤU ĐÁ", "Giải thích cách khóa 4 chấu giữ kim cương vĩnh cửu", "TAG: HUYK_GIAI_THICH_CHAU", (15, 30, 35), "person")
    create_graphic_card(f"{temp_dir}/c5.png", "HUYK CHÀO KẾT & KÊU GỌI CTA", "Mời ghé thăm showroom & đăng ký tư vấn phong thủy", "TAG: HUYK_OUTRO", (35, 15, 25), "person")

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=0x12141a:s=1080x1920:d=120:r=30",
        "-loop", "1", "-i", f"{temp_dir}/c1.png",
        "-loop", "1", "-i", f"{temp_dir}/c2.png",
        "-loop", "1", "-i", f"{temp_dir}/c3.png",
        "-loop", "1", "-i", f"{temp_dir}/c4.png",
        "-loop", "1", "-i", f"{temp_dir}/c5.png",
        "-filter_complex",
        "[0:v]drawbox=x=40:y=60:w=1000:h=120:color=black@0.7:t=fill,"
        "drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:text='VIDEO NGUỒN SỐ 2 - HUYK A-ROLL TALKING (120s)':x=70:y=90:fontsize=36:fontcolor=white:box=0,"
        "drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:text='THỜI GIAN GỐC\\: %{pts\\:hms} / 00\\:02\\:00':x=70:y=138:fontsize=30:fontcolor=0x4AE0C0,"
        "drawbox=x=40:y=1820:w=1000:h=40:color=white@0.2:t=fill,"
        "drawbox=x=40:y=1820:w='1000*t/120':h=40:color=0x4AE0C0:t=fill[base];"
        "[base][1:v]overlay=x=(W-w)/2:y=650:enable='between(t,0,25)'[v1];"
        "[v1][2:v]overlay=x=(W-w)/2:y=650:enable='between(t,25,50)'[v2];"
        "[v2][3:v]overlay=x=(W-w)/2:y=650:enable='between(t,50,75)'[v3];"
        "[v3][4:v]overlay=x=(W-w)/2:y=650:enable='between(t,75,100)'[v4];"
        "[v4][5:v]overlay=x=(W-w)/2:y=650:enable='between(t,100,120)',"
        "drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:text='VIDEO TALKING HEAD - THU ÂM CHUYÊN GIA':x=(w-text_w)/2:y=1750:fontsize=28:fontcolor=white@0.8[vout]",
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        output_file
    ]
    subprocess.run(cmd, check=True)
    print(f"✅ Đã tạo thành công: {output_file}")

def generate_video_3():
    """Sinh Video 3: 120 giây (2m00s) Sản phẩm thô & Hoàn thiện"""
    output_file = "mock_data/video_3_san_pham_source.mp4"
    temp_dir = "mock_data/temp_cards_v3"
    ensure_dir(temp_dir)
    print("🎬 Đang tạo Video 3 (120s - Sản phẩm & Showcase)...")

    create_graphic_card(f"{temp_dir}/c1.png", "SẢN PHẨM HOOK: BẢN VẼ & PHÔI THÔ", "Cận cảnh bản thiết kế 3D và viên kim cương thô tự nhiên", "TAG: SAN_PHAM_HOOK", (15, 20, 30), "diamond")
    create_graphic_card(f"{temp_dir}/c2.png", "CẬN CẢNH GÓC CẠNH NHẪN", "Zoom macro từng đường nét sắc sảo trên thân nhẫn", "TAG: SAN_PHAM_MACRO", (20, 20, 25), "diamond")
    create_graphic_card(f"{temp_dir}/c3.png", "BÀN XOAY 360 ĐỘ HOÀN THIỆN", "Showcase thành phẩm trên đế nhung đen phản chiếu lung linh", "TAG: SAN_PHAM_HOAN_THIEN_360", (25, 20, 10), "diamond")
    create_graphic_card(f"{temp_dir}/c4.png", "TRÊN TAY MẪU: ĐEO THỰC TẾ", "Trải nghiệm đeo thực tế tôn vinh khí chất quý phái", "TAG: SAN_PHAM_TREN_TAY", (30, 15, 10), "diamond")

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=0x08090d:s=1080x1920:d=120:r=30",
        "-loop", "1", "-i", f"{temp_dir}/c1.png",
        "-loop", "1", "-i", f"{temp_dir}/c2.png",
        "-loop", "1", "-i", f"{temp_dir}/c3.png",
        "-loop", "1", "-i", f"{temp_dir}/c4.png",
        "-filter_complex",
        "[0:v]drawbox=x=40:y=60:w=1000:h=120:color=black@0.7:t=fill,"
        "drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:text='VIDEO NGUỒN SỐ 3 - SHOWCASE SẢN PHẨM (120s)':x=70:y=90:fontsize=36:fontcolor=white:box=0,"
        "drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:text='THỜI GIAN GỐC\\: %{pts\\:hms} / 00\\:02\\:00':x=70:y=138:fontsize=30:fontcolor=0xE088E0,"
        "drawbox=x=40:y=1820:w=1000:h=40:color=white@0.2:t=fill,"
        "drawbox=x=40:y=1820:w='1000*t/120':h=40:color=0xE088E0:t=fill[base];"
        "[base][1:v]overlay=x=(W-w)/2:y=650:enable='between(t,0,30)'[v1];"
        "[v1][2:v]overlay=x=(W-w)/2:y=650:enable='between(t,30,60)'[v2];"
        "[v2][3:v]overlay=x=(W-w)/2:y=650:enable='between(t,60,95)'[v3];"
        "[v3][4:v]overlay=x=(W-w)/2:y=650:enable='between(t,95,120)',"
        "drawtext=fontfile=/System/Library/Fonts/Supplemental/Arial.ttf:text='FOOTAGE SƯU TẦM + QUAY SHOWROOM':x=(w-text_w)/2:y=1750:fontsize=28:fontcolor=white@0.8[vout]",
        "-map", "[vout]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        output_file
    ]
    subprocess.run(cmd, check=True)
    print(f"✅ Đã tạo thành công: {output_file}")

if __name__ == "__main__":
    generate_video_1()
    generate_video_2()
    generate_video_3()
    print("🎉 Hoàn tất tạo toàn bộ 3 video Testing Mock-up (độ dài 2-3 phút)!")
