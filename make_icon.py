from PIL import Image

src = r'C:\Users\Carvalho\.gemini\antigravity\brain\acec9fee-a747-4f26-98e5-5d48dd354203\bot_icon_1777042576016.png'
dst = r'c:\Users\Carvalho\Dev\ganharDolar\crypto-bot\icon.ico'

img = Image.open(src).convert('RGBA')
sizes = [(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
imgs = [img.resize(s, Image.LANCZOS) for s in sizes]
imgs[0].save(dst, format='ICO', sizes=sizes, append_images=imgs[1:])
print('OK:', dst)
