from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, Field
from langgraph.prebuilt import InjectedState
from langgraph.prebuilt.chat_agent_executor import AgentState
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from typing import Annotated




@tool("get_pdf_pages")
def get_pdf_pages(
    pdf_name: str,
    page: int,
    state: Annotated[AgentState, InjectedState]
):
    """This function gets specific page of a pdf file and returns its text discription
Args:
    pdf_name: pdf name that we need
    page: page number that we need
        """
    # get_pdf_pages(pdf_name ,page ,state["session_id"])
    pass

@tool("search_keyword")
def search_keyword(
    query: str,
    state: Annotated[AgentState, InjectedState],

) -> str:
    """Searching for a key word in documents
    
    Args:
        query: This is searched in the database
    """
    pass
    # searching(query,state["session_id"])
    
def document_loader():
    pass

def text_splitter():
    pass

def vector_store():
    pass

def embedding_model():
    pass

def retrieval_component():
    pass

def summarization():
    pass

