"""Strict public-indexer commands shared by authenticated control and cloud routes."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class IndexerCommand(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['list','configuration','save','remove','enabled','test']
    site: str | None = Field(default=None, pattern=r'^[a-zA-Z0-9_-]{1,100}$')
    revision: int | str | None = None
    enabled: bool | None = None
    values: dict[str, bool | str] = Field(default_factory=dict, max_length=100)
    confirm: bool = False

    @model_validator(mode='after')
    def valid_scope(self):
        if self.action!='list' and not self.site:raise ValueError('invalid_request')
        if self.action=='enabled' and (type(self.enabled) is not bool or type(self.revision) is not int or self.revision<0):
            raise ValueError('invalid_request')
        if self.action in ('save','remove'):
            import re
            if not isinstance(self.revision,str) or not re.fullmatch(r'[a-f0-9]{64}',self.revision):
                raise ValueError('invalid_request')
        if self.action=='remove' and not self.confirm:raise ValueError('confirmation_required')
        return self


def invoke_indexer(manager, command):
    return manager.invoke(**command.model_dump())
