import argparse
from transformers import AutoTokenizer, AutoModelForCausalLM
import torch
import os
import json
from tqdm import tqdm
import ray
from load_model import get_conversation_template

def disable_torch_init():
    """
    Disable the redundant torch default initialization to accelerate model creation.
    """
    import torch
    setattr(torch.nn.Linear, "reset_parameters", lambda self: None)
    setattr(torch.nn.LayerNorm, "reset_parameters", lambda self: None)


def run_eval(model_path, model_id, question_file, answer_file, num_gpus):
    # split question file into num_gpus files
    ques_jsons = []
    with open(os.path.expanduser(question_file), "r") as ques_file:
        for line in ques_file:
            ques_jsons.append(line)

    chunk_size = len(ques_jsons) // num_gpus
    ans_handles = []
    for i in range(0, len(ques_jsons), chunk_size):
        ans_handles.append(get_model_answers.remote(model_path, model_id, ques_jsons[i:i + chunk_size]))

    ans_jsons = []
    for ans_handle in ans_handles:
        ans_jsons.extend(ray.get(ans_handle))

    with open(os.path.expanduser(answer_file), "w") as ans_file:
        for line in ans_jsons:
            ans_file.write(json.dumps(line) + "\n")


@ray.remote(num_gpus=1)
@torch.inference_mode()
def get_model_answers(model_path, model_id, question_jsons):
    disable_torch_init()
    model_path = os.path.expanduser(model_path)
    tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast= False)
    model = AutoModelForCausalLM.from_pretrained(model_path,
        torch_dtype=torch.float16).cuda()

    ans_jsons = []
    for i, line in enumerate(tqdm(question_jsons)):
        ques_json = json.loads(line)
        idx = ques_json["question_id"]
        qs = ques_json["text"]
        print("initial question", qs)
        conv = get_conversation_template(model_id)
        conv.append_message(conv.roles[0], qs)
        conv.append_message(conv.roles[1], None)
        prompt = conv.get_prompt()

        inputs = tokenizer([prompt])
        output_ids = model.generate(
            torch.as_tensor(inputs.input_ids).cuda(),
            do_sample=True,
            temperature=0.7,
            max_new_tokens=1024)
        output_ids = output_ids[0][len(inputs.input_ids[0]) :]
        outputs = tokenizer.decode(output_ids, skip_special_tokens=True).strip()
        print("cleaned output",outputs)
        ans_jsons.append({"question_id": idx,
                          "text": outputs})
    return ans_jsons


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=str, default="")
    parser.add_argument("--model-id", type=str, default="alpaca")
    parser.add_argument("--question-file", type=str, default="../input_data/flask_evaluation_raw.jsonl")
    parser.add_argument("--answer-file", type=str, default="outputs/alpaca_7b.jsonl")
    parser.add_argument("--num-gpus", type=int, default=1)
    args = parser.parse_args()

    ray.init()
    run_eval(args.model_path, args.model_id, args.question_file, args.answer_file, args.num_gpus)
