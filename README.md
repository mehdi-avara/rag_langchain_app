# RAG LangChain Application

This project is a Retrieval-Augmented Generation (RAG) system built with LangChain, FastAPI, and Streamlit. It allows users to upload documents, browse them, and chat with an AI assistant that uses the documents as context.

## Prerequisites

- Docker and Docker Compose
- OpenAI API key
- Jina API key

## Setup

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd rag_langchain_app
   ```

2. Create a `.env` file in the root directory with the following variables:
   ```
   OPENAI_API_KEY=your_openai_api_key
   JINA_API_KEY=your_jina_api_key
   POSTGRES_URL=postgresql+psycopg2://rag:rag@postgres:5432/rag
   ELASTIC_HOST=http://elastic:9200
   CHROMA_PERSIST_DIR=/data/chroma
   JWT_SECRET=change_me
   JWT_EXP_HOURS=4
   ```

3. Build and start the Docker containers:
   ```bash
   docker-compose up --build
   ```

4. Access the application:
   - UI: http://localhost:8501
   - API: http://localhost:8000

## Usage

1. **Login**: Use the provided credentials to log in to the application.

2. **Upload Documents**: Navigate to the Upload page to upload PDF or image files.

3. **Browse Documents**: View and manage your uploaded documents on the Browse page.

4. **Chat**: Ask questions about your documents on the Chat page. The AI will use the documents as context to provide answers.

## Testing

Run all project and backend module tests:
```bash
python run_all_tests.py
```

Forward pytest flags after the script options:
```bash
python run_all_tests.py -q -x --tb=short
```

## Deployment

The application is containerized using Docker. Use the provided `docker-compose.yml` to deploy the services.

## API Conventions (Model Management)

Model management routes are grouped by purpose under `backend/model_management/routes/` and share a single naming convention:

- Base resource uses plural nouns: `/models`
- Nested resources use plural nouns: `/models/{model_id}/documents`, `/models/{model_id}/comments`
- Actions use verbs only when they represent non-CRUD behavior: `/models/{model_id}/ask`
- HTTP verbs map to standard CRUD semantics (`POST` create/link, `GET` list/read, `PATCH` update, `DELETE` unlink/delete)


A problem here is one thing that when I add a text it is ok but htere is a problem in adding to the chunks for semantic search
I should search and get this problem
