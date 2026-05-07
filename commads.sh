rsync -avz -e "ssh -p 3031" --exclude='.git/' --filter=':- .gitignore' \
  root@85.208.254.238:/home/ubuntu/rag_langchain_app/ /Users/mehdi/Mehdi/work/porsa_server/


# laptop: edit in VS Code
code ./myproject

# laptop: preview sync to server
rsync -avzn -e "ssh -p 3031" --exclude='.git/' --filter=':- .gitignore' \
  /Users/mehdi/Mehdi/work/porsa_server/ root@85.208.254.238:/home/ubuntu/rag_langchain_app/

# laptop: send changes to server
rsync -avz -e "ssh -p 3031" --exclude='.git/' --filter=':- .gitignore' \
  /Users/mehdi/Mehdi/work/porsa_server/ root@85.208.254.238:/home/ubuntu/rag_langchain_app/

# server: test and commit
ssh mehdi@SERVER_IP
cd /home/ubuntu/rag_langchain_app/
git status
git add .
git commit -m "Finish changes"
git push


cd backend
alembic -c alembic.ini upgrade head
python db/seed_rbac.py
cd ..
pytest backend/financial_management/tests/test_financial_management.py
