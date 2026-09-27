"""Modelos de domínio do motor (puros, sem dependência de nuvem)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median


def r2(x: float) -> float:
    return round(float(x) + 1e-9, 2)


def brl(x: float) -> str:
    """Formata em reais no padrão pt-BR: 1234.5 -> 'R$ 1.234,50' (o guardrail de saída entende este formato)."""
    inteiro, dec = f"{abs(float(x)):,.2f}".split(".")
    return f"{'-' if x < 0 else ''}R$ {inteiro.replace(',', '.')},{dec}"


@dataclass
class Divida:
    divida_id: str
    produto: str                 # cartao_rotativo | cheque_especial | emprestimo | crediario | outro
    saldo: float
    taxa_mensal: float           # ex.: 0.14 = 14% a.m.
    dias_atraso: int = 0
    parcela_atual: float = 0.0
    parcelas_restantes: int = 0
    consequencia: str = "nenhuma"  # negativacao | corte_servico | garantia | nenhuma
    descricao: str = ""
    instituicao: str = "Itaú"      # dívidas de outras instituições entram via Open Finance (só quitar/manter no MVP)
    fonte: str = "cadastro"        # cadastro | derivada_extrato | open_finance_simulado  (a interface rotula o que é simulado)

    @property
    def custo_mensal(self) -> float:
        """Juros que correm por mês sobre o saldo (o que a dívida custa se nada mudar)."""
        return r2(self.saldo * self.taxa_mensal)

    @property
    def rotativo(self) -> bool:
        """Sem parcela definida (rotativo/cheque): não tem prazo para acabar."""
        return not (self.parcela_atual and self.parcelas_restantes)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["custo_mensal"] = self.custo_mensal
        d["rotativo"] = self.rotativo
        return d


@dataclass
class PerfilFinanceiro:
    cliente_id: str
    nome: str
    meses: list[str]                       # "2025-10", ... (12 meses, do mais antigo ao mais novo)
    renda_mensal: list[float]
    essenciais_mensal: list[float]
    compromissos_mensal: list[float]       # parcelas fixas que ficam FORA do acordo
    dividas: list[Divida]
    tem_reserva: bool = False
    dia_pagamento_preferido: int = 10
    persona: bool = False              # True = persona sintética da demo (rotulada na interface)
    fonte: str = "csv"                 # csv | bigquery
    renda_informada: float | None = None   # renda confirmada pela cliente quando o extrato não traz entradas

    @property
    def sobra_mensal(self) -> list[float]:
        return [r2(r - e - c) for r, e, c in zip(self.renda_mensal, self.essenciais_mensal, self.compromissos_mensal)]

    @property
    def renda_mediana(self) -> float:
        return r2(median(self.renda_mensal)) if self.renda_mensal else 0.0

    @property
    def renda_desconhecida(self) -> bool:
        """Extrato sem entradas de renda (dados insuficientes): a experiência pergunta antes de calcular."""
        return self.renda_mediana <= 0 and self.renda_informada is None

    @property
    def essenciais_mediana(self) -> float:
        return r2(median(self.essenciais_mensal))

    @property
    def total_dividas(self) -> float:
        return r2(sum(d.saldo for d in self.dividas))

    @property
    def custo_total_mensal(self) -> float:
        return r2(sum(d.custo_mensal for d in self.dividas))

    @property
    def maior_atraso(self) -> int:
        return max((d.dias_atraso for d in self.dividas), default=0)

    def to_dict(self) -> dict:
        return {
            "cliente_id": self.cliente_id,
            "nome": self.nome,
            "meses": self.meses,
            "renda_mensal": self.renda_mensal,
            "essenciais_mensal": self.essenciais_mensal,
            "compromissos_mensal": self.compromissos_mensal,
            "sobra_mensal": self.sobra_mensal,
            "renda_mediana": self.renda_mediana,
            "essenciais_mediana": self.essenciais_mediana,
            "dividas": [d.to_dict() for d in self.dividas],
            "total_dividas": self.total_dividas,
            "custo_total_mensal": self.custo_total_mensal,
            "tem_reserva": self.tem_reserva,
            "dia_pagamento_preferido": self.dia_pagamento_preferido,
            "persona": self.persona,
            "fonte": self.fonte,
            "renda_informada": self.renda_informada,
            "renda_desconhecida": self.renda_desconhecida,
        }


@dataclass
class Capacidade:
    sobra_p25: float
    colchao: float
    sobra_segura: float
    parcela_maxima: float
    meses_fracos: list[str]
    respiros_ano: int
    sobra_mediana: float
    explicacao: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Plano:
    id: str                       # "A" | "B" | "C" | "PADRAO"
    tipo: str                     # avista | parcela_que_cabe | parcela_com_respiro | padrao
    nome: str
    saldo_base: float             # saldo após desconto
    desconto_pct: float
    desconto_valor: float
    parcela: float
    prazo: int                    # nº de parcelas pagas (sem contar respiros)
    prazo_nominal: int            # prazo + respiros
    taxa_mensal: float
    cet_anual: float
    total_pago: float
    respiros: int
    cabe: bool
    motivo: str
    meses_em_que_nao_cabe: list[str] = field(default_factory=list)
    valor_avista: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Acordo:
    acordo_id: str
    cliente_id: str
    plano_id: str
    parcela: float
    prazo: int
    taxa_mensal: float
    saldo_inicial: float
    saldo_devedor: float
    status: str                   # proposto | aceito | ativo | quitado | quebrado
    respiros_max: int
    respiros_usados: int = 0
    pagas: int = 0
    criado_em: str = ""
    proximo_vencimento: str = ""  # ISO date
    historico: list[dict] = field(default_factory=list)
    # cenário por dívida: cada componente é uma renegociação (parcela/prazo próprios); quitações ficam registradas
    componentes: list[dict] = field(default_factory=list)
    quitacoes: list[dict] = field(default_factory=list)

    @property
    def restantes(self) -> int:
        return max(0, self.prazo - self.pagas)

    @property
    def componentes_ativos(self) -> list[dict]:
        return [c for c in self.componentes if c.get("status", "ativo") == "ativo"]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["restantes"] = self.restantes
        return d
