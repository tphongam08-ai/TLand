# TLand v5 — Dynamic GIS Layers

TLand v5 แยก Frontend (Leaflet/PWA-friendly HTML) ออกจาก Backend (FastAPI) และเก็บ Layer ใน PostgreSQL + PostGIS โดยข้อมูลเดิมจาก `TLand_v4.html` ถูกแยกเป็น default seed ครบ 5 ชุด: 14 + 2 + 28 + 15 + 276 = **335 polygons**

## 1) รันทดสอบบนเครื่องด้วย Docker

1. ติดตั้ง Docker Desktop
2. เปิด Terminal/PowerShell ในโฟลเดอร์โปรเจกต์
3. รัน `docker compose up --build`
4. ทดสอบ API: `http://localhost:8000/api/health`
5. เปิด `TLand_v5.html` ผ่าน local web server เช่น VS Code Live Server

ครั้งแรกที่ฐานข้อมูลว่าง Backend จะ import ไฟล์ใน `data/` เป็น default layers อัตโนมัติ

## 2) API

- `GET /api/health` — health check
- `GET /api/layers` — รายการ Layer
- `GET /api/layers/{id}` — metadata + GeoJSON
- `POST /api/layers` — upload `.zip` Shapefile หรือ `.geojson/.json`
- `PUT /api/layers/{id}` — แก้ `name`, `color` หรือ `geojson`
- `DELETE /api/layers/{id}` — ลบ Layer

### Upload Shapefile
ZIP ต้องมีอย่างน้อย `.shp`, `.dbf`, `.shx` และควรมี `.prj` ด้วย ตัวอย่าง:

```bash
curl -X POST http://localhost:8000/api/layers \
  -F "file=@forest.zip" \
  -F "name=ป่าสงวนชุดใหม่" \
  -F "color=#16a34a" \
  -F "source_crs=wgs84_utm47"
```

`source_crs` ที่รองรับแบบย่อ:
- `wgs84_utm47` = EPSG:32647
- `wgs84` = EPSG:4326
- `indian1975_utm47` = Indian 1975 / UTM 47N พร้อม 7-parameter translation ที่กำหนดใน `main.py`
- หรือส่งค่า CRS ที่ pyproj อ่านได้ เช่น `EPSG:32647`

> **สำคัญ:** Indian 1954/1975 ในประเทศไทยมี datum transformation ได้หลายชุดตามแหล่งข้อมูล/หน่วยงาน หากต้องการความแม่นยำระดับงานรังวัด ควรตรวจสอบค่าพารามิเตอร์กับ metadata ของชุดข้อมูลจริงก่อนใช้งานเชิงกฎหมาย/แนวเขต

### Upload GeoJSON

```bash
curl -X POST http://localhost:8000/api/layers \
  -F "file=@my-layer.geojson" \
  -F "name=My Layer" \
  -F "color=#f59e0b"
```

GeoJSON ที่อัปโหลดควรเป็น WGS84 longitude/latitude (EPSG:4326)

## 3) เชื่อม Frontend กับ API

ใน `TLand_v5.html` ค่าเริ่มต้นคือ:

```js
const API_URL=(window.TLAND_API_URL||localStorage.getItem('tland_api_url')||'http://localhost:8000')
```

ก่อนนำขึ้น GitHub Pages ให้เปลี่ยน `http://localhost:8000` เป็น URL Backend จริง เช่น `https://tland-api.onrender.com` หรือ URL จาก Railway

Backend ต้องตั้ง `ALLOWED_ORIGINS=https://tphongam08-ai.github.io` (ถ้า GitHub Pages มี path ต่อท้าย ให้ Origin ยังคงเป็นโดเมนเท่านั้น)

## 4) Deploy บน Render

> แผน/โควตาฟรีของผู้ให้บริการเปลี่ยนได้ตามเวลา ให้ตรวจสอบหน้า pricing ปัจจุบันก่อน deploy

1. Push โฟลเดอร์นี้ขึ้น GitHub repository
2. สร้าง PostgreSQL database บน Render (ถ้า database ไม่มี PostGIS ให้ใช้ผู้ให้บริการ PostgreSQL ที่เปิด extension PostGIS ได้)
3. สร้าง Web Service จาก repo เดียวกัน เลือก Docker
4. ตั้ง Environment Variables:
   - `DATABASE_URL=<PostgreSQL connection string>`
   - `ALLOWED_ORIGINS=https://tphongam08-ai.github.io`
5. Deploy แล้วเปิด `/api/health`
6. นำ URL service ไปใส่ใน `TLand_v5.html` แล้ว push Frontend ขึ้น GitHub Pages

## 5) Deploy บน Railway

1. Push โปรเจกต์ขึ้น GitHub
2. New Project → Deploy from GitHub Repo
3. เพิ่ม PostgreSQL service ที่รองรับ PostGIS หรือใช้ PostGIS database ภายนอก
4. ตั้ง `DATABASE_URL` และ `ALLOWED_ORIGINS`
5. Railway จะ build จาก `Dockerfile`; expose/public domain ให้ service API
6. ทดสอบ `https://<your-domain>/api/health`
7. แก้ `API_URL` ใน Frontend เป็น domain นี้

## 6) iPad / Safari / PWA

`TLand_v5.html` คง Apple mobile web app meta tags, Apple Touch Icon และ layout เดิมจาก v4 ไว้ รวมถึง Leaflet touch/pinch zoom. วิธีใช้งาน: เปิด URL บน Safari → Share → **Add to Home Screen**

Dynamic Layer UI มีปุ่ม `＋`, upload, toggle, color picker และ delete. Popup แสดง attributes ทุก field. เมื่อ API ใช้งานได้ Frontend จะ cache Layer ลง `localStorage`; ถ้าครั้งต่อไป API ล่ม จะโหลด cache ล่าสุดแทนโดยอัตโนมัติ

> Safari `localStorage` มีขนาดจำกัด หาก Layer โตมาก ควรเปลี่ยน offline cache เป็น IndexedDB ในรุ่นถัดไป

## 7) โครงสร้างไฟล์

```text
main.py
requirements.txt
Dockerfile
docker-compose.yml
.env.example
TLand_v5.html
README.md
data/
  layers.json
  L1.geojson
  L2.geojson
  L3.geojson
  L4.geojson
  LSPK.geojson
```

## หมายเหตุด้าน production

เวอร์ชันนี้ยังไม่มีระบบ login/authorization ดังนั้นหากเปิด API สู่สาธารณะ ผู้ที่เข้าถึง endpoint สามารถ POST/PUT/DELETE ได้ ควรเพิ่ม authentication/API key ก่อนใช้งานจริงกับข้อมูลราชการหรือข้อมูลที่ไม่ควรแก้ไขโดยบุคคลทั่วไป
