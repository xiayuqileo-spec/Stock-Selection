#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import re

import tornado.httpserver
import tornado.ioloop
import tornado.web

from stock_analysis import analyze_stock


ROOT = os.path.dirname(os.path.abspath(__file__))


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        code = self.get_argument("code", "").strip()
        result = None
        error = None

        if code:
            if not re.fullmatch(r"\d{6}", code):
                error = "请输入 6 位股票代码，例如：600519。"
            else:
                try:
                    result = analyze_stock(code)
                except Exception as exc:
                    logging.exception("Failed to analyze %s", code)
                    error = f"实时分析失败：{exc}"

        self.render("index.html", code=code, result=result, error=error)


def make_app():
    return tornado.web.Application(
        [(r"/", MainHandler)],
        template_path=os.path.join(ROOT, "templates"),
        static_path=os.path.join(ROOT, "static"),
        debug=os.environ.get("DEBUG", "").lower() in ("1", "true", "yes"),
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9990))
    app = make_app()
    server = tornado.httpserver.HTTPServer(app)
    server.listen(port, address="0.0.0.0")
    print(f"选股已启动：http://0.0.0.0:{port}/")
    tornado.ioloop.IOLoop.current().start()
