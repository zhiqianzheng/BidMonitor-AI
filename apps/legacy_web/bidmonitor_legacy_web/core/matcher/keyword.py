"""
关键字匹配引擎
"""
import re
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class MatchResult:
    """匹配结果"""
    matched: bool
    matched_keywords: List[str]
    excluded_by: Optional[str] = None


class KeywordMatcher:
    """关键字匹配器"""
    
    def __init__(self, include_keywords: List[str], exclude_keywords: Optional[List[str]] = None,
                 must_contain_keywords: Optional[List[str]] = None, match_all: bool = False):
        """
        初始化匹配器
        
        Args:
            include_keywords: 包含关键字列表（OR关系，匹配任一即可）
            exclude_keywords: 排除关键字列表（匹配任一则排除）
            must_contain_keywords: 必须包含关键字列表（AND关系，必须匹配至少一个）
        """
        self.include_keywords = [kw.strip().lower() for kw in include_keywords if kw.strip()]
        self.exclude_keywords = [kw.strip().lower() for kw in (exclude_keywords or []) if kw.strip()]
        self.must_contain_keywords = [kw.strip().lower() for kw in (must_contain_keywords or []) if kw.strip()]
        self.match_all = match_all
    
    def match(self, text: str) -> MatchResult:
        """
        检查文本是否匹配
        
        匹配逻辑：
        1. 如果包含任一排除关键字 → 不匹配
        2. 如果设置了must_contain，必须包含其中至少一个 → 否则不匹配
        3. 如果包含任一include关键字 → 匹配
        
        Args:
            text: 待匹配文本
            
        Returns:
            MatchResult 对象
        """
        if not text:
            return MatchResult(matched=False, matched_keywords=[])
        
        text_lower = text.lower()
        
        # 1. 检查排除关键字
        for kw in self.exclude_keywords:
            if kw in text_lower:
                return MatchResult(
                    matched=False, 
                    matched_keywords=[], 
                    excluded_by=kw
                )
        
        # 2. 检查必须包含关键字（AND组）
        if self.must_contain_keywords:
            must_matched = False
            for kw in self.must_contain_keywords:
                if kw in text_lower:
                    must_matched = True
                    break
            if not must_matched:
                # 没有匹配任何必须包含的关键字
                return MatchResult(matched=False, matched_keywords=[])
        
        # 3. 检查包含关键字（OR组）
        matched_keywords = []
        for kw in self.include_keywords:
            if kw in text_lower:
                matched_keywords.append(kw)

        if not matched_keywords and not (self.match_all and not self.include_keywords):
            return MatchResult(matched=False, matched_keywords=[])
        
        # 也把匹配到的must_contain关键字加入
        for kw in self.must_contain_keywords:
            if kw in text_lower and kw not in matched_keywords:
                matched_keywords.append(kw)
        
        return MatchResult(
            matched=bool(matched_keywords) or (self.match_all and not self.include_keywords),
            matched_keywords=matched_keywords
        )
    
    def match_any(self, *texts: str) -> MatchResult:
        """
        检查多个文本，只要有一个匹配即可
        
        Args:
            texts: 多个待匹配文本
            
        Returns:
            MatchResult 对象
        """
        all_matched_keywords = []
        excluded_by = None
        matched = False
        
        for text in texts:
            result = self.match(text)
            matched = matched or result.matched
            if result.excluded_by:
                excluded_by = result.excluded_by
            all_matched_keywords.extend(result.matched_keywords)
        
        # 去重
        all_matched_keywords = list(set(all_matched_keywords))
        
        # 如果被排除，则返回不匹配
        if excluded_by:
            return MatchResult(
                matched=False,
                matched_keywords=[],
                excluded_by=excluded_by
            )
        
        return MatchResult(
            matched=matched,
            matched_keywords=all_matched_keywords
        )


class RegexMatcher:
    """正则表达式匹配器（高级用法）"""
    
    def __init__(self, patterns: List[str]):
        """
        初始化正则匹配器
        
        Args:
            patterns: 正则表达式模式列表
        """
        self.patterns = [re.compile(p, re.IGNORECASE) for p in patterns]
    
    def match(self, text: str) -> bool:
        """检查文本是否匹配任一正则模式"""
        if not text:
            return False
        
        for pattern in self.patterns:
            if pattern.search(text):
                return True
        return False
