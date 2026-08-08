import datetime as dt
from typing import List
from pydantic import BaseModel, HttpUrl, Field

class URLShortenRequest(BaseModel):
    url: HttpUrl = Field(..., description="The full original URL to be shortened")

class URLShortenResponse(BaseModel):
    short_code: str = Field(..., description="The unique short code identifier")

class DailyClicks(BaseModel):
    date: dt.date = Field(..., description="The date (YYYY-MM-DD) of recorded clicks")
    clicks: int = Field(..., description="Number of clicks on this date")

class LinkStatsResponse(BaseModel):
    short_code: str = Field(..., description="The short code identifier")
    original_url: str = Field(..., description="The target destination URL")
    total_clicks: int = Field(..., description="Total aggregate clicks recorded")
    unique_ips: int = Field(..., description="Count of distinct IP addresses that clicked the link")
    clicks_per_day: List[DailyClicks] = Field(default_factory=list, description="Per-day click distribution for the last 7 days")
