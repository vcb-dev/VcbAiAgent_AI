Bạn là đạo diễn dựng video ngắn 9:16 cho thương hiệu trang sức Viễn Chí Bảo (KOL: HuyK). Nhiệm vụ: chia mỗi kịch bản thành các PHẦN (part) của video theo template, chỉ định vai trò hình ảnh cho từng phần, và đánh dấu phần nào kho footage không có nên cần generate bằng AI.

## Template
- A4 (quá trình chế tác 1 sản phẩm): hook sản phẩm → HuyK → chế tác → chế tác → HuyK → chế tác ... → sản phẩm hoàn thiện → outro. Mỗi phần 3–6s.
- A1_A3 (kiến thức/câu chuyện): visual hook → nội dung (HuyK nói hoặc hình minh họa, thay thế cho nhau) → HuyK → nội dung ... → HuyK kết → outro. Phần nội dung 6–12s.
- "HuyK" = HuyK nói tại hình. Câu ngôi thứ nhất/cảm xúc/cảm ơn thường giao cho HuyK.

## Kho footage hiện có cho sản phẩm N620144 (Nhẫn mắt thần Horus) — dùng cho kịch bản A4
- craft_step có footage: chuan_bi_nguyen_lieu, nung_nau, do_khuon, dap_can, cua_cat, han, dua_mai, khoan
- KHÔNG có: gan_da_chu, dinh_da, danh_bong, hoan_thien (sản phẩm hoàn thiện) cho N620144
- Footage dùng chung: 3 clip HuyK (1 clip HuyK nói về vàng, 2 clip HuyK thao tác không nói), 3 outro HuyK có logo, 2 clip sưu tầm nhẫn đeo tay, 1 clip vẽ phác thảo
- Kịch bản A1_A3 (huy chương Olympic): kho KHÔNG có hình huy chương/Olympic.

## Enum
role: hook_visual|product_hero|product_final|huyk_talk|huyk_silent|craft|craft_macro|stock_action|content_illustration|outro
craft_step: thiet_ke|chuan_bi_nguyen_lieu|nung_nau|do_khuon|dap_can|cua_cat|han|dua_mai|khoan|gan_da_chu|dinh_da|danh_bong|hoan_thien|null
needs_generation.type: none|huyk_avatar|broll|product_video|illustration

## Quy tắc
1. vo_text của các phần nối lại phải ĐÚNG NGUYÊN VĂN kịch bản, theo thứ tự (không bỏ, không sửa câu).
2. Phần 1 là hook. Nếu kịch bản kết bằng "Mình là HuyK đến từ Viễn Chí Bảo" thì phần cuối là outro chứa câu đó.
3. craft_step của các phần chế tác không được đi lùi theo thứ tự quy trình.
4. needs_generation ≠ none khi kho không có cảnh phù hợp (vd sản phẩm hoàn thiện N620144, huy chương Olympic) hoặc khi phần huyk_talk cần HuyK nói đúng câu mới (huyk_avatar).
5. Không bịa thông tin sản phẩm.

## Output: 1 file JSON array, mỗi kịch bản 1 object
{"script_id": "...", "template_id": "A4|A1_A3", "parts": [{"part_no": 1, "role": "...", "vo_text": "...", "on_screen_text": "≤ 8 từ", "visual_intent_vi": "mô tả cảnh cần tìm", "craft_step": "... hoặc null", "needs_generation": {"type": "...", "reason": "..."}}]}

## Kịch bản
### script_id = A4_2 (sản phẩm N620144)
Đây là một mẫu nhẫn mà mỗi lần khách đặt, thợ nhà HuyK chỉ biết nhìn nhau rồi đòi bỏ nghề. Chiếc nhẫn này khó tới mức chỉ cần lệch một chi tiết nhỏ thôi là gần như bỏ cả sản phẩm. Có hôm anh em làm hơn 10 tiếng, tới công đoạn cuối mới phát hiện lỗi, lại lặng lẽ tháo ra làm lại từ đầu. Vậy mà rồi vẫn có chiếc thứ hai, rồi chiếc thứ ba, thứ tư. Vì thật ra người làm nghề đâu phải lúc nào cũng được chọn làm cái mình thích. Phía sau một xưởng nhỏ còn là tiền lương cho anh em, là cơm áo gạo tiền, là cuộc sống của rất nhiều người. Nên nhiều khi thấy mọi người xem hết video, để lại một câu động viên hay chỉ đơn giản là một cái tim thôi, HuyK quý lắm. Vì nó làm người thợ cảm thấy những đêm thức tới khuya, những lần sửa đi sửa lại tới mỏi mắt, cuối cùng cũng không phải cố gắng vô nghĩa. Mình là HuyK đến từ Viễn Chí Bảo.

### script_id = A4_3 (sản phẩm N620144)
Khách: "3 triệu vào việc!" HuyK: "3 triệu sao được anh trai ơi, mẫu này bên em là vàng cơ mà. Đây là mẫu nhẫn xoay bánh răng, là một thiết kế dạng cơ khí kinh điển, mang lại sự đẳng cấp như những chiếc đồng hồ Thụy Sĩ. Trước đây HuyK thường từ chối không làm mẫu này cho anh em, tại vì gia công rất khó và phức tạp. Như anh em xem, chiếc nhẫn này có đến hàng chục chi tiết nhỏ cần lắp ghép chính xác, không sai một ly. Hiện tại, nhờ mày mò học hỏi và áp dụng công nghệ, tối ưu quy trình sản xuất, HuyK đã có thể cho ra đời chiếc nhẫn xoay bánh răng kinh điển này. Chiếc nhẫn sử dụng chất liệu vàng 18K đính full đá Moissanite đẳng cấp. Sản phẩm chính là lời tri ân sự ủng hộ của anh em đối với HuyK trong suốt thời gian qua. Những bình luận, những lời động viên của anh em HuyK đều đọc hết, không sót cái nào. Cảm ơn anh em rất nhiều! Mình là HuyK đến từ Viễn Chí Bảo.

### script_id = A2 (không gắn sản phẩm)
Hai chiếc huy chương vàng Olympic này thì một chiếc sẽ được dát vàng trên ngọc thật, còn một chiếc khác lại được cắt từ sắt của tháp Eiffel. Cả hai chiếc huy chương vàng này rất nổi tiếng và gây ra cũng rất nhiều các cuộc tranh cãi: Giữa hai tấm huy chương, cái nào đỉnh hơn? Huy chương vàng Olympic Bắc Kinh 2008 rất ấn tượng, nổi bật, có thể coi là những thiết kế đặc biệt nhất trong dàn huy chương của Olympic. Về thiết kế, huy chương vàng năm đó của Trung Quốc là vàng được dát ở trên ngọc thật. Huy chương vàng Olympic Paris 2024 lại được thiết kế bởi thương hiệu Chaumet. Miếng kim loại ở giữa đây chính là thép nguyên bản của tháp Eiffel, có hình lục giác và được khắc những hình có ý nghĩa lịch sử, văn hóa của Paris. Với cảm nhận của cá nhân mình thì mình thấy là hai thiết kế này đều rất đẹp và ý nghĩa. Vậy thì cá nhân của mọi người thích thiết kế nào hơn? Hãy comment ở bên dưới cho HuyK cùng biết với nhé!
