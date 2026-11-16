"""Local scenario generators with auditable requests and strict validation."""
import json
from pathlib import Path
import urllib.request

from .disruptions import schema, validate_events


def post(url, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def parse_json(text):
    text = text.strip()
    if text.startswith('```') and text.endswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0]
    return json.loads(text)


def generate(config, model, provider='ollama', url='http://localhost:11434', seed=42, kind=None):
    zones = [z['id'] for z in config['zones']]
    output_schema = schema(zones)
    context = {k: config[k] for k in ('duration_minutes', 'zones', 'products', 'waves')}
    messages = [
        {'role': 'system', 'content': 'Generate one realistic cold-chain disruption scenario as JSON. '
         'Only emit description and disruptions. Generate at least one disruption. '
         'sensor_bias value is Celsius bias added to sensor reading, between -5 and +5. '
         'cooling_failure value is available cooling fraction between 0 and 1. '
         'door_stuck value must be 1. Use only existing zone IDs. '
         'Events must fit the horizon; same kind and zone events must not overlap. '
         'Do not change stock, temperatures, products, orders or physics parameters. '
         'Schema: '+json.dumps(output_schema)},
        {'role': 'user', 'content': 'Scenario seed '+str(seed)+'. Warehouse context: '+json.dumps(context)}]
    if kind is not None:
        if kind not in ('sensor_bias','cooling_failure','door_stuck'):
            raise ValueError('Unknown requested disruption kind')
        messages[0]['content'] += (' All events must use kind '+kind+'. '
            'For sensor bias prefer a negative reading bias so the physical zone warms rather than cooling below empirical temperature curves.')
    if provider == 'ollama':
        # Official API: https://docs.ollama.com/api/chat
        details = post(url.rstrip('/')+'/api/show', {'model': model})
        quantization = details.get('details', {}).get('quantization_level', 'unknown')
        if not quantization.upper().startswith(('Q4', 'IQ4')):
            raise ValueError(f'4-bit generation requires Q4/IQ4 Ollama model; reported {quantization}')
        request = {'model': model, 'stream': False, 'format': output_schema,
                   'messages': messages, 'options': {'temperature': 0.7, 'seed': seed}}
        response = post(url.rstrip('/')+'/api/chat', request)
        raw = response['message']['content']
        provenance = dict(provider=provider, model=model, quantization=quantization,
                          endpoint=url, seed=seed, request=request, response=response)
    elif provider == 'unsloth':
        # https://unsloth.ai/docs/basics/inference-and-deployment/unsloth-inference
        # Local paths only: loading this provider never implicitly downloads weights.
        if not Path(model).is_dir():
            raise ValueError('Unsloth model must be an existing local model directory')
        try:
            from unsloth import FastLanguageModel
            import torch
        except ImportError as exc:
            raise ValueError('Unsloth provider needs Unsloth, PyTorch and compatible GPU dependencies installed separately') from exc
        torch.manual_seed(seed)
        network, tokenizer = FastLanguageModel.from_pretrained(model_name=model, max_seq_length=8192,
                                                               load_in_4bit=True, local_files_only=True)
        FastLanguageModel.for_inference(network)
        inputs = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                               return_tensors='pt').to(network.device)
        outputs = network.generate(input_ids=inputs, max_new_tokens=1024, do_sample=True, temperature=0.7)
        raw = tokenizer.decode(outputs[0, inputs.shape[-1]:], skip_special_tokens=True)
        provenance = dict(provider=provider, model=str(Path(model).resolve()), quantization='load_in_4bit',
                          seed=seed, messages=messages, raw_response=raw)
    else:
        raise ValueError('Unknown LLM provider')
    scenario = parse_json(raw)
    if not isinstance(scenario, dict) or set(scenario) != {'description', 'disruptions'} or not isinstance(scenario['description'], str):
        raise ValueError('Model returned invalid scenario object')
    validate_events(scenario['disruptions'], zones, config['duration_minutes'])
    if not scenario['disruptions']:
        raise ValueError('Model generated no disruptions')
    if kind is not None and any(event['kind'] != kind for event in scenario['disruptions']):
        raise ValueError('Model response does not match requested disruption kind')
    return dict(scenario, generation=provenance)


def apply_scenario(config, scenario):
    validate_events(scenario['disruptions'], [z['id'] for z in config['zones']], config['duration_minutes'])
    config['disruptions'] = scenario['disruptions']
    config['scenario_provenance'] = {k: v for k, v in scenario.items() if k != 'disruptions'}
    return config
