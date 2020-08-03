from typing import Union, List, Iterable, Iterator, TYPE_CHECKING, Callable, Tuple
from pathlib import Path
import random

from .. import util
from .example import Example
from ..tokens import DocBin, Doc
from ..vocab import Vocab

if TYPE_CHECKING:
    # This lets us add type hints for mypy etc. without causing circular imports
    from ..language import Language  # noqa: F401


@util.registry.readers("spacy.Corpus.v1")
def create_docbin_reader(
    gold_preproc: bool,
    max_length: int=0,
    limit: int=0
) -> Callable[["Language", Path], Iterable[Example]]:
    return Corpus(gold_preproc=gold_preproc, max_length=max_length, limit=limit)


class Corpus:
    """Iterate Example objects from a file or directory of DocBin (.spacy)
    formated data files.

    gold_preproc (bool): Whether to set up the Example object with gold-standard
        sentences and tokens for the predictions. Gold preprocessing helps 
        the annotations align to the tokenization, and may result in sequences
        of more consistent length. However, it may reduce run-time accuracy due
        to train/test skew. Defaults to False.
    max_length (int): Maximum document length. Longer documents will be
        split into sentences, if sentence boundaries are available. Defaults to
        0, which indicates no limit.
    limit (int): Limit corpus to a subset of examples, e.g. for debugging.
        Defaults to 0, which indicates no limit.

    DOCS: https://spacy.io/api/corpus
    """
    def __init__(
        self,
        *,
        limit: int = 0,
        gold_preproc: bool=False,
        max_length: bool=False,
    ) -> None:
        self.gold_preproc = gold_preproc
        self.max_length = max_length
        self.limit = limit

    @staticmethod
    def walk_corpus(path: Union[str, Path]) -> List[Path]:
        path = util.ensure_path(path)
        if not path.is_dir():
            return [path]
        paths = [path]
        locs = []
        seen = set()
        for path in paths:
            if str(path) in seen:
                continue
            seen.add(str(path))
            if path.parts[-1].startswith("."):
                continue
            elif path.is_dir():
                paths.extend(path.iterdir())
            elif path.parts[-1].endswith(".spacy"):
                locs.append(path)
        return locs

    def __call__(
        self,
        nlp: "Language",
        loc: Union[Path, str],
    ) -> Iterator[Example]:
        """Yield examples from the data.

        nlp (Language): The current nlp object.
        loc (Path): The file or directory to read from.
        YIELDS (Example): The examples.

        DOCS: https://spacy.io/api/corpus#train_dataset
        """
        loc = util.ensure_path(loc)
        ref_docs = self.read_docbin(nlp.vocab, self.walk_corpus(loc))
        if self.gold_preproc:
            examples = self.make_examples_gold_preproc(nlp, ref_docs)
        else:
            examples = self.make_examples(nlp, ref_docs, self.max_length)
        yield from examples

    def count(self, nlp: "Language", loc) -> int:
        """Returns count of words in train examples.

        nlp (Language): The current nlp. object.
        RETURNS (int): The word count.

        DOCS: https://spacy.io/api/corpus#count_train
        """
        n = 0
        i = 0
        for example in self(nlp, loc):
            n += len(example.predicted)
            if self.limit >= 0 and i >= self.limit:
                break
            i += 1
        return n

    def _make_example(
        self, nlp: "Language", reference: Doc, gold_preproc: bool
    ) -> Example:
        if gold_preproc or reference.has_unknown_spaces:
            return Example(
                Doc(
                    nlp.vocab,
                    words=[word.text for word in reference],
                    spaces=[bool(word.whitespace_) for word in reference],
                ),
                reference,
            )
        else:
            return Example(nlp.make_doc(reference.text), reference)

    def make_examples(
        self, nlp: "Language", reference_docs: Iterable[Doc], max_length: int = 0
    ) -> Iterator[Example]:
        for reference in reference_docs:
            if len(reference) == 0:
                continue
            elif max_length == 0 or len(reference) < max_length:
                yield self._make_example(nlp, reference, False)
            elif reference.is_sentenced:
                for ref_sent in reference.sents:
                    if len(ref_sent) == 0:
                        continue
                    elif max_length == 0 or len(ref_sent) < max_length:
                        yield self._make_example(nlp, ref_sent.as_doc(), False)

    def make_examples_gold_preproc(
        self, nlp: "Language", reference_docs: Iterable[Doc]
    ) -> Iterator[Example]:
        for reference in reference_docs:
            if reference.is_sentenced:
                ref_sents = [sent.as_doc() for sent in reference.sents]
            else:
                ref_sents = [reference]
            for ref_sent in ref_sents:
                eg = self._make_example(nlp, ref_sent, True)
                if len(eg.x):
                    yield eg

    def read_docbin(
        self, vocab: Vocab, locs: Iterable[Union[str, Path]]
    ) -> Iterator[Doc]:
        """ Yield training examples as example dicts """
        i = 0
        for loc in locs:
            loc = util.ensure_path(loc)
            if loc.parts[-1].endswith(".spacy"):
                with loc.open("rb") as file_:
                    doc_bin = DocBin().from_bytes(file_.read())
                docs = doc_bin.get_docs(vocab)
                for doc in docs:
                    if len(doc):
                        yield doc
                        i += 1
                        if self.limit >= 1 and i >= self.limit:
                            break
