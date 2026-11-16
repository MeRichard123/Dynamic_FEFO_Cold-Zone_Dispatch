"""Print a small zero-shot picking prompt, then its dataset reference answer.

Run: python3 EDA.py
Only copy the text between the prompt markers into your LLM.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    with (ROOT / 'dataset/train.jsonl').open(encoding='utf-8') as stream:
        example = json.loads(next(stream))

    user_input = next(m['content'] for m in example['messages']
                      if m['role'] == 'user')
    # The original message has other JSON blocks after the warehouse state.
    state, _ = json.JSONDecoder().raw_decode(user_input[user_input.index('{'):])
    answer = json.loads(next(m['content'] for m in example['messages']
                             if m['role'] == 'assistant'))

    # Keep only the inputs needed for this simplified pick-order exercise.
    inputs = {
        'orders': [
            {key: wave[key] for key in ('at_minute', 'sku', 'quantity_kg')}
            for wave in state['waves']
        ],
        'pallets': [
            {key: pallet[key] for key in
             ('id', 'sku', 'quantity_kg', 'remaining_life_hours', 'reserved')}
            for pallet in state['initial_pallets']
        ],
    }
    prompt = (
        'You are a warehouse dispatch assistant. Choose the pallet pick order.\n'
        'Process orders in the listed order. Within each order, pick available,\n'
        'unreserved pallets of the matching SKU with the shortest remaining life\n'
        'first. Use enough stock to satisfy the order. Remaining life is in hours;\n'
        'quantities are in kg.\n\n'
        'Return only a JSON object with a "pick_priorities" array. Each entry\n'
        'must contain "pallet_id" and "priority" (integer starting at 1).\n'
        'Use only the supplied pallet IDs.\n\n'
        'Warehouse data:\n' + json.dumps(inputs, indent=2)
    )
    ground_truth = {'pick_priorities': answer['dispatch_plan']['pick_priorities']}

    print('ZERO-SHOT TEST | first training example')
    print('Task: simplified pick ordering; no worked examples are included.')
    print('\n========== PROMPT START ==========\n')
    print(prompt)
    print('\n========== PROMPT END ==========')
    print('\nGROUND TRUTH — evaluation only; do not send this to the LLM.')
    print('Pick priorities taken from the simulation-generated dataset answer.')
    print(json.dumps(ground_truth, indent=2))


if __name__ == '__main__':
    main()
