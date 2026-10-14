#!/usr/bin/env python3
"""
Tạo các file âm thanh Mock-up cho hệ thống:
1. voiceover_sample.wav: Giọng đọc kịch bản thuyết minh (~45s)
2. bgm_luxury.wav: Nhạc nền phong cách trang sức sang trọng (~50s)
3. sfx_torch.wav: Âm thanh khò lửa nung vàng (~5s)
4. sfx_hammer.wav: Âm thanh gõ búa đe kim hoàn (~5s)
5. sfx_sparkle.wav: Âm thanh chuông ngân lấp lánh khi lộ sản phẩm (~5s)
"""
import os
import wave
import struct
import math
import random

SAMPLE_RATE = 44100

def write_wav(filename, samples, sample_rate=SAMPLE_RATE):
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with wave.open(filename, 'w') as wf:
        wf.setnchannels(1)  # Mono
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        # Clamp & pack
        packed = bytearray()
        for s in samples:
            val = max(-32767, min(32767, int(s * 32767)))
            packed.extend(struct.pack('<h', val))
        wf.writeframes(packed)
    print(f"🎵 Đã tạo audio: {filename} ({len(samples)/sample_rate:.1f}s)")

def generate_voiceover(output_path, duration=45.0):
    """
    Tạo dạng sóng mô phỏng giọng nói thuyết minh có ngắt nghỉ câu rõ ràng
    tương ứng với cấu trúc kịch bản 9 khối của Video A4
    """
    total_samples = int(duration * SAMPLE_RATE)
    samples = [0.0] * total_samples
    
    # Định nghĩa các phân đoạn có tiếng nói (Voice active intervals)
    # Khối 1: 0.5s - 4.5s
    # Khối 2: 5.2s - 8.8s
    # Khối 3: 9.3s - 13.5s
    # Khối 4: 14.2s - 17.8s
    # Khối 5: 18.3s - 22.7s
    # Khối 6: 23.2s - 26.8s
    # Khối 7: 27.3s - 31.7s
    # Khối 8: 32.5s - 39.5s
    # Khối 9: 40.2s - 44.5s
    speech_intervals = [
        (0.5, 4.5, 140, "Hook sản phẩm"),
        (5.2, 8.8, 145, "HuyK mở đầu"),
        (9.3, 13.5, 138, "Chế tác 1 nung lửa"),
        (14.2, 17.8, 148, "HuyK chia sẻ bí quyết"),
        (18.3, 22.7, 142, "Chế tác 2 cưa dũa"),
        (23.2, 26.8, 150, "HuyK nhấn mạnh độ tỉ mỉ"),
        (27.3, 31.7, 144, "Chế tác 3 vào chấu kim cương"),
        (32.5, 39.5, 140, "Sản phẩm hoàn thiện lộng lẫy"),
        (40.2, 44.5, 146, "Outro HuyK chào kết & Viễn Chí Bảo")
    ]
    
    for start_t, end_t, base_pitch, desc in speech_intervals:
        start_idx = int(start_t * SAMPLE_RATE)
        end_idx = int(end_t * SAMPLE_RATE)
        num_sp_samples = end_idx - start_idx
        
        for i in range(num_sp_samples):
            t = i / SAMPLE_RATE
            # Envelope mềm ở đầu và cuối câu
            env = 1.0
            ramp = 0.08 * SAMPLE_RATE
            if i < ramp:
                env = i / ramp
            elif i > num_sp_samples - ramp:
                env = (num_sp_samples - i) / ramp
            
            # Voice pitch modulation (nhịp điệu ngữ điệu tiếng nói)
            pitch = base_pitch + 12.0 * math.sin(2 * math.pi * 1.8 * t) + 6.0 * math.sin(2 * math.pi * 3.5 * t)
            
            # Formant harmonics mô phỏng giọng nam trầm ấm
            f0 = math.sin(2 * math.pi * pitch * t)
            f1 = 0.6 * math.sin(2 * math.pi * (pitch * 2) * t)
            f2 = 0.35 * math.sin(2 * math.pi * (pitch * 3) * t)
            f3 = 0.15 * math.sin(2 * math.pi * (pitch * 4) * t)
            # Thêm âm xát (consonant noise) nhẹ
            noise = (random.random() * 2 - 1) * 0.05 * math.sin(2 * math.pi * 5 * t)
            
            val = (f0 + f1 + f2 + f3 + noise) * 0.45 * env
            samples[start_idx + i] = val
            
    write_wav(output_path, samples)

def generate_bgm_luxury(output_path, duration=50.0):
    """
    Tạo nhạc nền ambient lofi sang trọng, êm dịu phù hợp video trang sức
    Hợp âm rải (Arpeggio) Cmaj9 -> Am9 -> Fmaj7 -> Gsus4
    """
    total_samples = int(duration * SAMPLE_RATE)
    samples = [0.0] * total_samples
    
    # Chuỗi hợp âm (tần số nốt nhạc Hz)
    chords = [
        [130.81, 164.81, 196.00, 246.94, 293.66],  # Cmaj9
        [110.00, 130.81, 164.81, 196.00, 246.94],  # Am9
        [87.31, 130.81, 174.61, 220.00, 261.63],   # Fmaj7
        [98.00, 146.83, 196.00, 261.63, 293.66]    # Gsus4
    ]
    
    chord_len = 4.0 # 4 giây mỗi hợp âm
    
    for i in range(total_samples):
        t = i / SAMPLE_RATE
        chord_idx = int(t / chord_len) % len(chords)
        chord_notes = chords[chord_idx]
        
        # Nhịp arpeggio nhẹ nhàng (nốt đánh lần lượt mỗi 0.5s)
        sub_beat = int((t % chord_len) * 2) % len(chord_notes)
        note_freq = chord_notes[sub_beat]
        
        # Bass note nền ngân dài
        bass_freq = chord_notes[0]
        bass_wave = math.sin(2 * math.pi * bass_freq * t) * 0.25
        
        # Melody arpeggio với decay ấm
        beat_t = (t % 0.5)
        melody_env = math.exp(-beat_t * 5.0)
        melody_wave = math.sin(2 * math.pi * note_freq * t) * melody_env * 0.2
        
        # Pad ấm tần số cao
        pad = math.sin(2 * math.pi * (chord_notes[2] * 2) * t) * 0.08
        
        # Tổng hợp
        val = (bass_wave + melody_wave + pad) * 0.35
        # Fade out ở 2s cuối
        if t > duration - 2.0:
            val *= (duration - t) / 2.0
        samples[i] = val
        
    write_wav(output_path, samples)

def generate_sfx(torch_path, hammer_path, sparkle_path):
    # 1. SFX Torch (Khò lửa nung kim loại)
    dur = 5.0
    tot = int(dur * SAMPLE_RATE)
    samples_torch = [0.0] * tot
    for i in range(tot):
        t = i / SAMPLE_RATE
        # Noise lọc thông thấp mô phỏng tiếng lửa phì phì
        raw_noise = random.random() * 2 - 1
        # Envelope phồng lên ở giữa
        env = math.sin(math.pi * t / dur)
        val = raw_noise * 0.25 * env * (0.8 + 0.2 * math.sin(2 * math.pi * 35 * t))
        samples_torch[i] = val
    write_wav(torch_path, samples_torch)
    
    # 2. SFX Hammer (Tiếng gõ búa đe kim hoàn)
    samples_hammer = [0.0] * tot
    # Gõ 4 nhát tại các giây: 0.5, 1.6, 2.7, 3.8
    hits = [0.5, 1.6, 2.7, 3.8]
    for hit_t in hits:
        hit_idx = int(hit_t * SAMPLE_RATE)
        hit_dur_samples = int(0.6 * SAMPLE_RATE)
        for i in range(hit_dur_samples):
            if hit_idx + i >= tot:
                break
            t = i / SAMPLE_RATE
            # Kim loại va chạm: 1800Hz + 3200Hz decay nhanh
            env = math.exp(-t * 22.0)
            metal_ring = (math.sin(2 * math.pi * 1850 * t) + 0.6 * math.sin(2 * math.pi * 3420 * t)) * env * 0.45
            # Thump trầm của đe
            thump = math.sin(2 * math.pi * 220 * t) * math.exp(-t * 35.0) * 0.3
            samples_hammer[hit_idx + i] += metal_ring + thump
    write_wav(hammer_path, samples_hammer)
    
    # 3. SFX Sparkle (Chuông gió lấp lánh khi khoe sản phẩm)
    samples_sparkle = [0.0] * tot
    sparkle_freqs = [2400, 2800, 3200, 3600, 4200, 4800, 5600]
    for _ in range(35): # 35 tiếng ting nhỏ rải rác
        ting_t = random.uniform(0.2, 4.5)
        ting_idx = int(ting_t * SAMPLE_RATE)
        f = random.choice(sparkle_freqs)
        ting_len = int(0.4 * SAMPLE_RATE)
        for i in range(ting_len):
            if ting_idx + i >= tot:
                break
            t = i / SAMPLE_RATE
            env = math.exp(-t * 12.0)
            val = math.sin(2 * math.pi * f * t) * env * 0.08
            samples_sparkle[ting_idx + i] += val
    write_wav(sparkle_path, samples_sparkle)

if __name__ == "__main__":
    from pathlib import Path

    here = Path(__file__).resolve().parent          # VCB_AI/assets — nơi renderer đọc tài nguyên
    generate_voiceover(str(here / "voiceover_sample.wav"), duration=45.0)
    generate_bgm_luxury(str(here / "bgm_luxury.wav"), duration=50.0)
    generate_sfx(
        str(here / "sfx_torch.wav"),
        str(here / "sfx_hammer.wav"),
        str(here / "sfx_sparkle.wav"),
    )
    print("✅ Hoàn tất sinh toàn bộ tài nguyên âm thanh Mock-up!")
