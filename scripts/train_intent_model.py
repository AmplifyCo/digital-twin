import argparse
from datasets import load_dataset
from transformers import AutoTokenizer, AutoModelForSequenceClassification, Trainer, TrainingArguments
from sklearn.metrics import accuracy_score
import numpy as np

def compute_metrics(p):
    preds = np.argmax(p.predictions, axis=1)
    return {"accuracy": accuracy_score(p.label_ids, preds)}

def main(args):
    # Load dataset
    dataset = load_dataset("csv", data_files=args.data, split="train")
    dataset = dataset.train_test_split(test_size=0.2)

    # Labels (adjust based on your intents)
    labels = sorted(set(dataset["train"]["label"]))
    label2id = {label: i for i, label in enumerate(labels)}
    id2label = {i: label for label, i in label2id.items()}

    # Tokenizer and model
    tokenizer = AutoTokenizer.from_pretrained("distilbert-base-uncased")
    model = AutoModelForSequenceClassification.from_pretrained(
        "distilbert-base-uncased", num_labels=len(labels), id2label=id2label, label2id=label2id
    )

    # Tokenize function
    def tokenize(examples):
        tokenized = tokenizer(examples["text"], truncation=True, padding="max_length", max_length=128)
        tokenized["labels"] = [label2id[l] for l in examples["label"]]
        return tokenized

    tokenized_dataset = dataset.map(tokenize, batched=True)

    # Training args (CPU-friendly)
    training_args = TrainingArguments(
        output_dir=args.output,
        num_train_epochs=3,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        weight_decay=0.01,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        no_cuda=True,  # Force CPU
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset["train"],
        eval_dataset=tokenized_dataset["test"],
        tokenizer=tokenizer,
        compute_metrics=compute_metrics,
    )

    trainer.train()
    trainer.save_model(args.output)
    print(f"Model saved to {args.output}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, help="Path to CSV dataset")
    parser.add_argument("--output", default="intent_model", help="Output directory")
    main(parser.parse_args())