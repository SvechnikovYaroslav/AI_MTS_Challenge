interface Card {
  title: string;
  example: string;
}

const CARDS: Card[] = [
  {
    title: 'Снизить затраты на электроэнергию',
    example: 'Расходы предприятия на электричество выросли. Что можно сделать?',
  },
  {
    title: 'Автоматизировать учёт',
    example: 'У нас несколько магазинов. Можно контролировать их потребление в одном кабинете?',
  },
  {
    title: 'Солнечные электростанции',
    example: 'Хотим установить солнечные панели на складе. С чего начать?',
  },
  {
    title: 'Контроль коммерческих потерь',
    example: 'Наша электросетевая компания хочет эффективнее выявлять подозрительные точки учёта.',
  },
];

interface Props {
  onSelect: (text: string) => void;
  disabled?: boolean;
}

export function WelcomeScreen({ onSelect, disabled }: Props) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 py-8">
      <div className="w-full max-w-2xl text-center">
        <h2 className="text-2xl font-bold text-slate-900 sm:text-3xl">
          Как мы можем помочь вашему бизнесу?
        </h2>
        <p className="mt-3 text-sm text-slate-600 sm:text-base">
          Расскажите о своей задаче — консультант поможет разобраться в решениях МТС EnergyTool.
        </p>

        <div className="mt-8 grid gap-3 sm:grid-cols-2">
          {CARDS.map((card) => (
            <button
              key={card.title}
              onClick={() => onSelect(card.example)}
              disabled={disabled}
              className="group rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition-all hover:border-mts-red/40 hover:shadow-md disabled:opacity-50"
            >
              <div className="text-sm font-semibold text-slate-900 group-hover:text-mts-red">
                {card.title}
              </div>
              <div className="mt-2 text-xs leading-relaxed text-slate-500">{card.example}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
