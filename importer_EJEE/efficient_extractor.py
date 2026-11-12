"""Save mapped question/solution together while retaining native crop tools."""


PROFILE = 'mapped-pair-v1'
INSTRUCTIONS = """MAPPED IMAGE EXECUTION MODE (takes precedence over tool names above):
All mapped source images are already supplied. Read every continuation. Do not
request the same pages again. This tool set contains assisted_crop, exact_crop
and submit_pair. Keep the original assisted/exact retry and quality checks.
Reviewed diagrams already exist: reference them without recropping. Never invent
missing diagrams or solutions. Inspect the ONE final source-pixel preview per
crop and repair clipping/foreign text with the same filename.
When ready, submit BOTH question and solution in ONE submit_pair call. This runs
the SAME native PaperLab compile/save validators in order. Repair NOT SAVED
responses. Do not spend a separate model turn just to save the other half.
All original transcription, answer-key, statement-only and diagram quality rules
remain mandatory. White display padding does not fix clipped source content.
"""

def build_tools(native,manifest,item,tool_decorator=None):
    if tool_decorator is None:
        from langchain_core.tools import tool
    else:tool=tool_decorator
    pid=manifest['paper_id'];number=item['number']

    def identity(paper_id,question_number):
        if paper_id!=pid or str(question_number)!=number:raise ValueError('Wrong mapped question identity')

    @tool
    def submit_pair(paper_id:int,question_number:str,question_latex:str,solution_latex:str,qtype:str='unknown')->str:
        """Validate/save both LaTeX sides, question first. Use no_solution_found only for a missing source solution/key. Native type codes and answer-key rules still apply."""
        identity(paper_id,question_number)
        q=native.submit_question.invoke({'paper_id':pid,'question_number':number,'latex_content':question_latex,'qtype':qtype})
        if q!='saved':return 'QUESTION NOT SAVED: '+str(q)
        s=native.submit_solution.invoke({'paper_id':pid,'question_number':number,'latex_content':solution_latex})
        return 'saved' if s=='saved' else 'SOLUTION NOT SAVED: '+str(s)

    return [native.assisted_crop,native.exact_crop,submit_pair]


def prune_old_preview(content,filename):
    """Retain old correction text, but send only the newest image per figure."""
    if (isinstance(content,list) and content and isinstance(content[0],dict)
            and str(content[0].get('text','')).startswith(filename+': ')):
        return [block for block in content if not isinstance(block,dict) or block.get('type')!='image_url']
    return content
