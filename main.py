import json, os, shutil, tempfile, zipfile
from pathlib import Path
from typing import Optional
import shapefile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pyproj import CRS, Transformer
from sqlalchemy import create_engine, text

DATABASE_URL=os.getenv('DATABASE_URL','postgresql://user:pass@db:5432/tland')
ALLOWED_ORIGINS=[x.strip() for x in os.getenv('ALLOWED_ORIGINS','*').split(',') if x.strip()]
engine=create_engine(DATABASE_URL,pool_pre_ping=True)
app=FastAPI(title='TLand GIS API',version='5.0.0')
app.add_middleware(CORSMiddleware,allow_origins=ALLOWED_ORIGINS or ['*'],allow_credentials=False,allow_methods=['*'],allow_headers=['*'])

class LayerUpdate(BaseModel):
    name: Optional[str]=None
    color: Optional[str]=None
    geojson: Optional[dict]=None

def init_db():
    with engine.begin() as c:
        c.execute(text('CREATE EXTENSION IF NOT EXISTS postgis'))
        c.execute(text('''CREATE TABLE IF NOT EXISTS layers(
          id SERIAL PRIMARY KEY,name TEXT NOT NULL,color TEXT NOT NULL DEFAULT '#3b82f6',
          geojson JSONB NOT NULL, geom geometry(Geometry,4326), is_default BOOLEAN DEFAULT FALSE,
          created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())'''))

def save_layer(name,color,gj,is_default=False):
    payload=json.dumps(gj,ensure_ascii=False)
    sql=text('''INSERT INTO layers(name,color,geojson,geom,is_default)
      VALUES(:name,:color,CAST(:gj AS jsonb),ST_SetSRID(ST_GeomFromGeoJSON(CAST(:geom AS json)),4326),:d)
      RETURNING id''')
    geom={'type':'GeometryCollection','geometries':[f['geometry'] for f in gj.get('features',[]) if f.get('geometry')]}
    with engine.begin() as c:
        return c.execute(sql,{'name':name,'color':color,'gj':payload,'geom':json.dumps(geom),'d':is_default}).scalar_one()

def seed_defaults():
    base=Path(__file__).parent/'data'
    if not (base/'layers.json').exists(): return
    with engine.begin() as c:
        if c.execute(text('SELECT count(*) FROM layers')).scalar_one()>0:return
    for item in json.loads((base/'layers.json').read_text(encoding='utf-8')):
        gj=json.loads((base/item['file']).read_text(encoding='utf-8'))
        save_layer(item['name'],item['color'],gj,True)

@app.on_event('startup')
def startup():
    init_db(); seed_defaults()

@app.get('/api/health')
def health():
    with engine.connect() as c: c.execute(text('SELECT 1'))
    return {'status':'ok','service':'tland-api'}

@app.get('/api/layers')
def list_layers():
    with engine.connect() as c:
        rows=c.execute(text("SELECT id,name,color,is_default,jsonb_array_length(COALESCE(geojson->'features','[]'::jsonb)) feature_count FROM layers ORDER BY id")).mappings().all()
    return [dict(r) for r in rows]

@app.get('/api/layers/{layer_id}')
def get_layer(layer_id:int):
    with engine.connect() as c:
        r=c.execute(text('SELECT id,name,color,is_default,geojson FROM layers WHERE id=:id'),{'id':layer_id}).mappings().first()
    if not r: raise HTTPException(404,'Layer not found')
    return dict(r)

def shapefile_to_geojson(folder:Path, source_crs:Optional[str]):
    shp=next(folder.rglob('*.shp'),None); dbf=next(folder.rglob('*.dbf'),None); shx=next(folder.rglob('*.shx'),None)
    if not all([shp,dbf,shx]): raise HTTPException(400,'ZIP ต้องมี .shp .dbf .shx')
    prj=next(folder.rglob('*.prj'),None)
    crs=None
    if source_crs:
        aliases={'wgs84_utm47':'EPSG:32647','wgs84':'EPSG:4326','indian1975_utm47':'+proj=utm +zone=47 +a=6377276.345 +rf=300.8017 +towgs84=204,837,294,0,0,0,0 +units=m +no_defs'}
        crs=CRS.from_user_input(aliases.get(source_crs,source_crs))
    elif prj:
        try: crs=CRS.from_wkt(prj.read_text(errors='ignore'))
        except Exception: pass
    if crs is None: raise HTTPException(400,'ไม่พบ/อ่าน .prj ไม่ได้ กรุณาส่ง source_crs เช่น EPSG:32647 หรือ indian1975_utm47')
    tf=Transformer.from_crs(crs,'EPSG:4326',always_xy=True)
    rd=shapefile.Reader(str(shp),encoding='utf-8',encodingErrors='replace')
    fields=[f[0] for f in rd.fields[1:]]; features=[]
    for sr in rd.iterShapeRecords():
        geo=sr.shape.__geo_interface__
        def tr(c):
            if isinstance(c,(list,tuple)) and len(c)>=2 and isinstance(c[0],(int,float)): return list(tf.transform(c[0],c[1]))
            return [tr(x) for x in c]
        geo={'type':geo['type'],'coordinates':tr(geo['coordinates'])}
        props={k:v for k,v in zip(fields,list(sr.record))}
        features.append({'type':'Feature','properties':props,'geometry':geo})
    return {'type':'FeatureCollection','features':features}

@app.post('/api/layers')
async def upload_layer(file:UploadFile=File(...),name:Optional[str]=Form(None),color:str=Form('#3b82f6'),source_crs:Optional[str]=Form(None)):
    suffix=Path(file.filename or '').suffix.lower(); data=await file.read()
    try:
        if suffix in ('.geojson','.json'):
            gj=json.loads(data.decode('utf-8-sig'))
            if gj.get('type')!='FeatureCollection': raise HTTPException(400,'GeoJSON ต้องเป็น FeatureCollection')
        elif suffix=='.zip':
            with tempfile.TemporaryDirectory() as td:
                zpath=Path(td)/'upload.zip'; zpath.write_bytes(data)
                with zipfile.ZipFile(zpath) as z:
                    for m in z.infolist():
                        target=(Path(td)/'shape'/m.filename).resolve()
                        if not str(target).startswith(str((Path(td)/'shape').resolve())): raise HTTPException(400,'Unsafe ZIP path')
                    z.extractall(Path(td)/'shape')
                gj=shapefile_to_geojson(Path(td)/'shape',source_crs)
        else: raise HTTPException(400,'รองรับเฉพาะ .zip Shapefile หรือ .geojson/.json')
    except HTTPException: raise
    except Exception as e: raise HTTPException(400,f'อ่านไฟล์ไม่สำเร็จ: {e}')
    lid=save_layer(name or Path(file.filename or 'Layer').stem,color,gj)
    return {'id':lid,'name':name or Path(file.filename or 'Layer').stem,'feature_count':len(gj.get('features',[]))}

@app.put('/api/layers/{layer_id}')
def update_layer(layer_id:int,body:LayerUpdate):
    sets=[]; p={'id':layer_id}
    if body.name is not None: sets.append('name=:name');p['name']=body.name
    if body.color is not None: sets.append('color=:color');p['color']=body.color
    if body.geojson is not None:
        sets += ['geojson=CAST(:gj AS jsonb)','geom=ST_SetSRID(ST_GeomFromGeoJSON(CAST(:geom AS json)),4326)']
        p['gj']=json.dumps(body.geojson,ensure_ascii=False)
        p['geom']=json.dumps({'type':'GeometryCollection','geometries':[f['geometry'] for f in body.geojson.get('features',[]) if f.get('geometry')]})
    if not sets:return {'ok':True}
    sets.append('updated_at=now()')
    with engine.begin() as c:
        r=c.execute(text('UPDATE layers SET '+','.join(sets)+' WHERE id=:id RETURNING id'),p).first()
    if not r: raise HTTPException(404,'Layer not found')
    return {'ok':True,'id':layer_id}

@app.delete('/api/layers/{layer_id}')
def delete_layer(layer_id:int):
    with engine.begin() as c:
        r=c.execute(text('DELETE FROM layers WHERE id=:id RETURNING id'),{'id':layer_id}).first()
    if not r: raise HTTPException(404,'Layer not found')
    return {'ok':True}
