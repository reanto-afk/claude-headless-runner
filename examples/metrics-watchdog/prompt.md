Você é uma rotina sem humano no terminal. Não faça perguntas e não edite arquivos.

1. Rode exatamente: `python check_metrics.py --today 2026-11-09`
2. Com base SÓ no JSON que o script imprimir, escreva um resumo em pt-BR de no máximo 8 linhas:
   - a data de referência;
   - o que está ok;
   - o que está vazio, separando "a rotina pode preencher (valor da fonte)" de "avisar o dono";
   - o que diverge da fonte de verdade, com a diferença em %.
   Não invente números nem cite o conteúdo de campos de texto.
3. Se o script falhar ou não imprimir JSON, a última linha deve ser `RUN_FAILED: <motivo curto>`.
   Caso contrário, a última linha deve ser exatamente `RUN_OK`.
