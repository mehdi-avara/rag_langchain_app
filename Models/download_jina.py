from transformers import AutoModel, AutoTokenizer

# Specify custom directory
custom_path = "Models"

model = AutoModel.from_pretrained(
            'jinaai/jina-embeddings-v3', 
                cache_dir=custom_path,
                    trust_remote_code=True
                    )
tokenizer = AutoTokenizer.from_pretrained(
            'jinaai/jina-embeddings-v3',
                cache_dir=custom_path
                )