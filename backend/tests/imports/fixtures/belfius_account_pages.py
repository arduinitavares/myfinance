"""Module for backend tests imports fixtures belfius_account_pages."""

from typing import Any

SANITIZED_BELFIUS_PAGE_TEXTS: Any = [
    (
        "Belfius Bank NV\n"
        "Karel Rogierplein 11 - 1210 Brussel\n"
        "BEATS STAR-REKENING\n"
        "Arduini Tavares Alexandre\n"
        "GEBRS VANDEVELDESTR 46/101                        DATUM :      16-02-2026\n"
        "9000  GENT\n"
        "                                                  BLZ. :              2/1\n"
        "-----------------  BE46 0636 5194 6836  BIC: GKCCBEBB  ------------------\n"
        "SALDO OP   15-01-2026                    EUR                    +   55,01\n"
        "0008  16-01-2026  (VAL. 16-01-2026)                             -  572,20\n"
        "  MASTERCARD AFREKENING NUMMER 007\n"
        "0009  16-01-2026  (VAL. 16-01-2026)                             +  637,00\n"
        "  INSTANT STORTING VAN\n"
        "  MT50 CFTE 2800 4000 0000 0000 1608 098 Alexandre\n"
        "  Arduini Tavares credit card payment NXT1QzMot-Hxt4Kqph\n"
        "  NAAR BE46 0636 5194 6836 Alexandre Augusto Tavares\n"
        "0010  16-01-2026  (VAL. 16-01-2026)                             -  637,00\n"
        "  INSTANT OVERSCHRIJVING BELFIUS MOBILE NAAR\n"
        "  BE11 9502 1298 4548 ALEXANDRE ARDUINI TAVARES Loan to\n"
        "  pay loan\n"
    ),
    (
        "Belfius Bank NV\n"
        "Karel Rogierplein 11 - 1210 Brussel\n"
        "                               16-02-2026                             2/2\n"
        "-------------------------  BE46 0636 5194 6836  -------------------------\n"
        "0011  19-01-2026  (VAL. 16-01-2026)                             -   43,56\n"
        "  BANCONTACT - AANKOOP - AZ Sint-Lucas - 9000 Gent BE -\n"
        "  16/01/26 22:59 - 776003339729 - VIA INTERNET - KAART\n"
        "  5169 20XX XXXX 0612 - Arduini Tavares A\n"
        "SALDO OP   16-02-2026 20:52              EUR                    -  127,38\n"
        "JAARLIJKSE RENTEVOET DEBETINTRESTEN:  9,500%\n"
        "DIT PRODUCT IS BESCHERMD DOOR HET GARANTIEFONDS.\n"
    ),
    (
        "Belfius Bank NV\n"
        "Karel Rogierplein 11 - 1210 Brussel\n"
        "                               16-02-2026                             2/3\n"
        "BIJLAGE BIJ VERRICHTING 11\n"
        "-------------------------  BE46 0636 5194 6836  -------------------------\n"
        "                           BEWIJSSTUK IN EUR\n"
        "   INTERESTEN REKENING BE46 0636 5194 6836\n"
        "        AFSLUITING INTERESTEN\n"
    ),
    (
        "Belfius Bank NV\n"
        "Karel Rogierplein 11 - 1210 Brussel\n"
        "                               16-02-2026                             2/4\n"
        "MEDEDELING PRODUCT\n"
        "-------------------------  BE46 0636 5194 6836  -------------------------\n"
        "   WIJZIGINGEN VAN DE REGLEMENTEN\n"
    ),
]
