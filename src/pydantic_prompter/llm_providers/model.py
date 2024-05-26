import inspect
import json
import logging
from abc import ABC
from random import uniform
from typing import List, Optional, Dict

from jinja2 import Template

from pydantic_prompter.common import Message

logger = logging.getLogger()


class Model(ABC):
    system_role_supported = True
    add_llama_special_tokens = True

    def __init__(self, model_name: str, model_settings: Optional[Dict] = None):
        if model_settings is None:
            model_settings = {}
        self.model_settings = model_settings
        self.model_name = model_name

    def bedrock_format(self, msgs: List[Message]):
        raise NotImplementedError

    def fix_and_merge_messages(self, msgs: List[Message]) -> List[Message]:
        # merge messages if roles do not alternate between "user" and "assistant"
        fixed_messages = []
        for m in msgs:
            if not self.system_role_supported and m.role == "system":
                m.role = "user"
            if fixed_messages and fixed_messages[-1].role == m.role:
                fixed_messages[-1].content += f"\n\n{m.content}"
            else:
                fixed_messages.append(m)
        return fixed_messages

    def system_message_jinja2(self):
        pmpt = """Act like a REST API that performs the requested operation the user asked according to guidelines provided.
                {% if return_type == 'json' %}
                    Your response should be a valid JSON format, strictly adhering to the Pydantic schema provided in the json_schema section. 
                    Respond in a structured JSON format according to the provided schema.

                ```json_schema
                    {{ schema }}
                ```
                {% else %}
                        Your response should be a valid {{ return_type }} only
                {% endif %}
                        Stick to the facts and details in the provided data, and follow the guidelines closely.
                        DO NOT add any other text other than the {{ return_type }} response
                    """
        return inspect.cleandoc(pmpt)

    def assistant_hint_jinja2(self):
        pmpt = """
            {% if return_type == 'json' %}
                ```{{ return_type }}
            {% else %}
            {% endif %}
                """
        return inspect.cleandoc(pmpt)

    def build_prompt(
        self, messages: List[Message], params: dict | str
    ) -> List[Message]:
        import json

        template = Template(self.system_message_jinja2(), keep_trailing_newline=True)

        if isinstance(params, dict):
            content = template.render(
                schema=json.dumps(params, indent=4), return_type="json"
            ).strip()

            hint = (
                Template(self.assistant_hint_jinja2())
                .render(return_type="json")
                .strip()
            )
        else:
            content = template.render(schema=params, return_type=params).strip()
            hint = (
                Template(self.assistant_hint_jinja2())
                .render(return_type=params)
                .strip()
            )

        messages.insert(0, Message(role="system", content=content))
        messages.append(Message(role="assistant", content=hint))
        messages = self.fix_and_merge_messages(messages)

        return messages


class GPT(Model):
    def system_message_jinja2(self):
        pass

    def assistant_hint_jinja2(self):
        pass


class Llama2(Model):
    def __init__(self, model_name: str):
        super().__init__(model_name)

    def fix_and_merge_messages(self, msgs: List[Message]) -> List[Message]:
        msgs = super().fix_and_merge_messages(msgs)
        if self.add_llama_special_tokens:
            for msg in msgs:
                if msg.role == "system":
                    msg.content = f"<<SYS>> {msg.content} <</SYS>>"
                if msg.role == "user":
                    msg.content = f"[INST] {msg.content} [/INST]"
        return msgs

    def bedrock_format(self, msgs: List[Message]):
        final_messages = "\n".join([m.content for m in msgs])
        import json
        from random import uniform

        body = json.dumps(
            {
                "max_gen_len": self.model_settings.get("max_gen_len") or 2048,
                "prompt": final_messages,
                "temperature": self.model_settings.get("temperature") or uniform(0, 1),
            }
        )
        return body


class CohereCommand(Model):

    #     def system_message_jinja2(self):
    #         pmp = """Act like a REST API
    # {% if return_type == 'json' %}
    # Your response should be within a JSON markdown block in JSON format
    # with the schema specified in the json_schema markdown block.
    #
    # ```json_schema
    # {{ schema }}
    # ```
    # {% else %}
    # Your response should be {{ return_type }} only
    # {% endif %}
    #
    # DO NOT add any other text other than the JSON response
    # """
    #         return pmp

    # def assistant_hint_jinja2(self):
    #     return """{% if return_type == 'json' %}
    #             ```json
    #             {% else %}
    #             {% endif %}
    #             """
    #     # return "Chatbot: ```{{ return_type }}\n"

    def bedrock_format(self, msgs: List[Message]):
        content = self.format_messages(msgs)
        prompt = "\n".join([f"{c['role']}: {c['message']}" for c in content])
        body = json.dumps(
            {
                "prompt": prompt,
                "stop_sequences": self.model_settings.get("stop_sequences")
                or ["User:"],
                "temperature": self.model_settings.get("temperature") or uniform(0, 1),
            }
        )
        return body

    # @staticmethod
    # def format_messages(msgs: List[Message]) -> str:
    #     role_converter = {"user": "User", "system": "System", "assistant": "Chatbot"}
    #     output = []
    #     for msg in msgs:
    #         output.append(f"{role_converter[msg.role]}: {msg.content}")
    #     return "\n".join(output)

    @staticmethod
    def format_messages(msgs: List[Message]) -> List[dict]:
        role_converter = {"user": "USER", "system": "USER", "assistant": "CHATBOT"}
        output = []
        for msg in msgs:
            if msg.role == "system":
                msg.content = f"## Instructions\n{msg.content}"
            output.append({"role": role_converter[msg.role], "message": msg.content})
        return output


class CohereCommandR(CohereCommand):

    #     def system_message_jinja2(self):
    #         pmp = """Act like a REST API
    # {% if return_type == 'json' %}
    # Your response should be within a JSON markdown block in JSON format
    # with the schema specified in the json_schema markdown block.
    #
    # ```json_schema
    # {{ schema }}
    # ```
    # {% else %}
    # Your response should be {{ return_type }} only
    # {% endif %}
    #
    # DO NOT add any other text other than the JSON response
    # """
    #         return pmp

    # def assistant_hint_jinja2(self):
    #     return """{% if return_type == 'json' %}
    #             ```json
    #             {% else %}
    #             {% endif %}
    #             """
    #     # return "Chatbot: ```{{ return_type }}\n"

    def bedrock_format(self, msgs: List[Message]):
        content: List[dict] = self.format_messages(msgs)
        prompt = "\n".join([f"{c['role']}: {c['message']}" for c in content])
        body = json.dumps(
            {
                # "chat_history": content[1:],
                "message": prompt,
                "max_tokens": 20000,
                "stop_sequences": self.model_settings.get("stop_sequences")
                or ["User:"],
                "temperature": self.model_settings.get("temperature") or uniform(0, 1),
            }
        )
        return body


class Claude(Model):
    system_role_supported = True

    def bedrock_format(self, msgs: List[Message]):
        system_message = msgs.pop(0)
        final_messages = [m.dict() for m in msgs]
        body = json.dumps(
            {
                "system": system_message.content,
                "max_tokens": self.model_settings.get("max_tokens") or 8000,
                "messages": final_messages,
                # "stop_sequences": ["Human:"],
                "temperature": self.model_settings.get("temperature") or uniform(0, 1),
                "anthropic_version": self.model_settings.get("anthropic_version")
                or "bedrock-2023-05-31",
            }
        )
        return body
