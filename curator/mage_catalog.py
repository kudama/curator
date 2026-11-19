"""Normalize the provider's advertised image schemas without inventing models/options."""
import math
import re
from .errors import UserError


def options(architecture, model, field):
    value=(architecture.get('options_by_model',{}).get(model,{}) or {}).get(field)
    if value is None:value=architecture.get('options',{}).get(field)
    if value is None:value=architecture.get('input_schema',{}).get('properties',{}).get(field,{}).get('enum')
    return value if isinstance(value,list) else []


def models(catalog):
    result=[]
    for architecture in catalog.get('architectures',[]):
        if not isinstance(architecture,dict) or architecture.get('type','image' if architecture.get('id')=='mango' else '')!='image':continue
        name=architecture.get('id','')
        if not isinstance(name,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,60}',name):continue
        properties=architecture.get('input_schema',{}).get('properties',{})
        variants=properties.get('model_id',{}).get('enum')
        if variants is None:variants=[(architecture.get('base_config') or {}).get('model_id')] if 'model_id' in properties else [None]
        if not isinstance(variants,list):continue
        for model in variants:
            if model is not None and (not isinstance(model,str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,120}',model)):continue
            key=model if name=='mango' and model else name+(':'+model if model else '')
            label={'mango':'Mango','mango-v2':'Mango 2','mango-v3':'Mango 3','mango-v4':'Mango 4','mango-v3-turbo':'Mango 3 Turbo','mango-v3s':'Mango 3S'}.get(model,model or architecture.get('name') or name)
            reason='' if 'prompt' in properties and ('aspect_ratio' in properties or {'width','height'}<=set(properties)) else 'This model needs output controls not yet advertised for artwork'
            references=architecture.get('image_inputs',{}).get('references',{}) or {}
            result.append(dict(id=key,model_id=model,architecture=name,name=label,group='Mango' if name=='mango' else 'Other image models',
                resolutions=[str(v) for v in options(architecture,model,'resolution')],ratios=options(architecture,model,'aspect_ratio'),
                references=bool(references.get('field') or 'image' in properties or name=='mango'),supported=not reason,reason=reason))
    preferred={'mango-v2':0,'mango-v3':1,'mango-v4':2}
    return sorted(result,key=lambda r:(r['architecture']!='mango',preferred.get(r['id'],3),r['name'].casefold()))


def resolve(catalog, selected):
    row=next((row for row in models(catalog) if row['id']==selected),None)
    if not row:raise UserError('Selected Mage model is not in the current image catalog')
    if not row['supported']:raise UserError(row['reason'])
    architecture=next(a for a in catalog['architectures'] if a['id']==row['architecture'])
    return architecture,row


def request_body(architecture,row,settings,reference_images):
    properties=architecture.get('input_schema',{}).get('properties',{});body={'prompt':settings['prompt']}
    if row['model_id'] is not None:body['model_id']=row['model_id']
    ratio=settings['ratio'];resolution=settings.get('resolution','')
    if 'aspect_ratio' in properties:
        if ratio not in row['ratios']:raise UserError('Selected Mage model does not advertise this artwork ratio')
        body['aspect_ratio']=ratio
    else:
        w,h=map(int,ratio.split(':'));bounds=[]
        for field in ('width','height'):
            schema=properties[field]
            if schema.get('type')!='integer':raise UserError('Unsupported image dimension schema')
            bounds.append(int(schema.get('maximum',2048)))
        unit=min(bounds[0]//(w*8),bounds[1]//(h*8));body.update(width=w*8*unit,height=h*8*unit)
    if 'resolution' in properties or row['resolutions']:
        if resolution not in row['resolutions']:raise UserError('Selected Mage model does not advertise this resolution')
        body['resolution']=next(v for v in options(architecture,row['model_id'],'resolution') if str(v)==resolution)
    if settings.get('negative_prompt'):
        if 'negative_prompt' not in properties:raise UserError('Selected model has no documented negative prompt field')
        body['negative_prompt']=settings['negative_prompt']
    if reference_images:
        inputs=architecture.get('image_inputs',{}).get('references',{}) or {}
        first=inputs.get('field') or ('image' if row['references'] else None)
        additional=inputs.get('additional_field') or ('additional_images' if row['architecture']=='mango' else None)
        maximum=architecture.get('max_images_by_model',{}).get(row['model_id'],architecture.get('max_images',10 if row['architecture']=='mango' else 1))
        if not first or type(maximum) is not int or len(reference_images)>maximum or len(reference_images)>1 and not additional:
            raise UserError('Selected model does not advertise these reference inputs')
        body[first]=reference_images[0]
        if len(reference_images)>1:body[additional]=reference_images[1:]
    required=set(architecture.get('input_schema',{}).get('required',[]))
    defaults=architecture.get('base_config',{})
    if required-set(body)-set(defaults):raise UserError('Selected model requires additional controls before generation')
    for field,value in body.items():
        schema=properties.get(field,{})
        if type(value) in (int,float):
            if not math.isfinite(value) or value<schema.get('minimum',1) or value>schema.get('maximum',8192) or value%schema.get('multipleOf',1):
                raise UserError('Image dimensions are outside the selected model schema')
    return body
