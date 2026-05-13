
def main():
    print("Hello from sast!")

    from transformers import AutoProcessor, AutoModelForImageTextToText

    import os
    from dotenv import load_dotenv
    load_dotenv()

    hf_token = os.getenv("HF_TOKEN")

    if hf_token is None:
        raise ValueError("HF_TOKEN not found in .env file")

    processor = AutoProcessor.from_pretrained("Qwen/Qwen3.5-4B")
    model = AutoModelForImageTextToText.from_pretrained("Qwen/Qwen3.5-4B")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "url": "https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/p-blog/candy.JPG"},
                {"type": "text", "text": "What animal is on the candy?"}
            ]
        },
    ]
    inputs = processor.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)

    outputs = model.generate(**inputs, max_new_tokens=40)
    print(processor.decode(outputs[0][inputs["input_ids"].shape[-1]:]))


if __name__ == "__main__":
    main()
