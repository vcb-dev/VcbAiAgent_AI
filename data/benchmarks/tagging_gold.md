Bạn là chuyên viên phân loại footage xưởng kim hoàn (thương hiệu Viễn Chí Bảo, KOL HuyK).
Mỗi clip có 1 contact sheet 12 frame (4×3, mốc thời gian in góc trên trái). Dùng Read tool để xem ảnh.
Ảnh tham chiếu HuyK (người đàn ông nói chuyện trong clip này là HuyK): /Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_0a8d1c7d.jpg
Chỉ dùng giá trị enum. Không bịa SKU. Nếu không chắc, giảm conf.
Đây là bài test chỉ dựa vào hình ảnh: không có tên file hay thư mục.

## Taxonomy (dùng đúng giá trị enum)
roles (đa trị, mỗi role có conf 0..1): hook_visual (cảnh mở gây tò mò), product_hero (sản phẩm cận/xoay/trên tay),
product_final (sản phẩm hoàn thiện, reveal), huyk_talk (HuyK nói tại hình, thấy miệng), huyk_silent (HuyK xuất hiện không nói),
craft (thao tác chế tác), craft_macro (cận cực gần chi tiết), craft_pov (góc nhìn tay thợ), stock_action (hành động chung không gắn sản phẩm),
content_illustration (hình minh họa chủ đề), outro (kết thương hiệu có logo).
craft_step (1 giá trị hoặc null): thiet_ke (vẽ phác thảo/thiết kế), chuan_bi_nguyen_lieu (cân/đổ hạt kim loại),
nung_nau (khò lửa nung chảy kim loại trong chén), do_khuon (rót kim loại nóng chảy vào khuôn), dap_can (búa đập/cán thỏi, tạo phôi),
cua_cat (cưa lọng, cắt phần thừa), han (hàn nối điểm nhỏ), dua_mai (giũa, mài định hình), khoan (khoan lỗ/hốc đá/chi tiết),
gan_da_chu (gắn viên đá chủ lớn vào ổ), dinh_da (đính đá nhỏ/đá viền, soi kiểm đá), danh_bong (đánh bóng, làm sáng),
hoan_thien (sản phẩm đã xong: trưng bày, đeo thử, xoay).
shot_size: extreme_close|close|medium|wide · camera: static|handheld|pov|gimbal
subject (đa trị): hands|huyk_face|person|product|tool|fire|metal|stone|workshop|paper
product_type: nhan|day_chuyen|lac_tay|bong_tai|khac|none · metal: bac|vang|vang_trang|unknown
lighting: good|dark|overexposed|mixed · text_or_watermark: none|own_logo|third_party|subtitle_text
motion_level: 0..3 · aesthetic: 1..5 (đẹp để lên video quảng cáo trang sức)
## Output JSON cho MỖI clip
{"id": "...", "roles": [{"role": "...", "conf": 0.9}], "craft_step": "... hoặc null", "craft_step_conf": 0.8,
 "shot_size": "...", "camera": "...", "subject": ["..."], "huyk_present": true/false, "person_speaking_to_camera": true/false,
 "product_visible": true/false, "product_type": "...", "metal": "...", "stone_color": ["xanh lá"], "lighting": "...",
 "text_or_watermark": "...", "motion_level": 2, "aesthetic": 4, "best_moment_s": 6.0, "usable_from_s": 0.5, "usable_to_s": 14.0,
 "description_vi": "mô tả ≤ 30 từ, tiếng Việt có dấu", "keywords_vi": ["5-10 từ khóa tiếng Việt"]}
best_moment_s / usable_*: đọc từ mốc thời gian in trên từng frame của contact sheet.

## Clips
- id=c_fd886a1a · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_fd886a1a.jpg · duration=15.26s
- id=c_7ad267ac · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_7ad267ac.jpg · duration=26.82s
- id=c_0a8d1c7d · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_0a8d1c7d.jpg · duration=58.07s
- id=c_8a5fc438 · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_8a5fc438.jpg · duration=22.94s
- id=c_840577db · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_840577db.jpg · duration=4.07s
- id=c_9746542f · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_9746542f.jpg · duration=14.2s
- id=c_f74a8bd7 · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_f74a8bd7.jpg · duration=15.47s
- id=c_945a3887 · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_945a3887.jpg · duration=18.27s
- id=c_a2dbfeee · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_a2dbfeee.jpg · duration=14.91s
- id=c_41a68bc5 · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_41a68bc5.jpg · duration=15.67s
- id=c_37e95497 · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_37e95497.jpg · duration=22.04s
- id=c_71b6151f · sheet=/Users/brianle/Documents/Code/Vidtory/VienChiBao-TrangSuc/mvp/media/sheets/c_71b6151f.jpg · duration=9.06s

Ghi KẾT QUẢ thành 1 file JSON array (mỗi phần tử là object clip ở trên) tại đường dẫn được giao.
