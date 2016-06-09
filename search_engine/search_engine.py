import math
import operator
import re

from django.core.exceptions import ObjectDoesNotExist

from search.models import Page, Word, Match
from src.build_index import BuildIndex
from src.html_to_text_converter import HtmlToTextConverter
from django.db.models import Avg

EPS = 1e-6

class SearchEngine:

    def create_index(self, url):
        # url = "http://fapl.ru/"
        htmlToTextConverter = HtmlToTextConverter()
        title, content = htmlToTextConverter.transform_html_into_text(url)
        buildIndex = BuildIndex(content)
        index = buildIndex.get_index()
        number_of_words = buildIndex.get_number_of_words()
        try:
            document = Page.objects.get(url=url)
            for match in Match.objects.filter(page=document):
                word = match.word
                match.delete()
                if not word.pages.all():
                    word.delete()
        except ObjectDoesNotExist:
            document = Page(url=url, number_of_words=number_of_words,
                            title=title, content=content)
            document.save()
        for word in index.keys():
            positions = " ".join(str(x) for x in index[word])
            try:
                word = Word.objects.get(value=word)
            except ObjectDoesNotExist:
                word = Word(value=word)
                word.save()
            match = Match(word=word, page=document, positions=positions)
            match.save()

    def delete_index(self, url):
        document = Page.objects.get(url=url)
        for match in Match.objects.filter(page=document):
            word = match.word
            match.delete()
            if not word.pages.all():
                word.delete()
        document.delete()

    def search_one_word(self, value):
        # import pdb; pdb.set_trace()
        pattern = re.compile(r'[\W_]+')
        value = pattern.sub('', value)
        result_pages = []
        try:
            word = Word.objects.get(value=value)            
        except ObjectDoesNotExist:
            return result_pages

        matches = Match.objects.filter(word=word)
        for match in matches:
            page = Page.objects.get(id=match.page_id)
            result_pages.append(page.url)

        return result_pages

    def _split_text_on_words(self, text):
        pattern = re.compile(r'[\W_]+')
        return pattern.sub(' ', text).split()

    def search_text(self, text):
        list_of_results = []
        words = self._split_text_on_words(text.lower())
        if not words:
            return list_of_results
        for word in words:
                list_of_results.append(self.search_one_word(word))
        return self.rank_results(words, list(set(list_of_results[0]).intersection(*list_of_results)))

    def search_phrase(self, phrase):
        # import pdb; pdb.set_trace()
        list_of_results = []
        words = self._split_text_on_words(phrase.lower())
        if not words:
            return list_of_results
        for word in words:
            list_of_results.append(self.search_one_word(word))
        setted = set(list_of_results[0]).intersection(*list_of_results)
        result = []
        for page in setted:
            temp = []
            for word in words:
                w = Word.objects.get(value=word)
                match = Match.objects.get(page=page, word=w)
                positions=[]
                for pos in match.positions.split():
                    positions.append(int(pos))
                temp.append(positions)
            for i in xrange(len(temp)):
                for j in xrange(len(temp[i])):
                    temp[i][j] -= i
            if set(temp[0]).intersection(*temp):
                result.append(url)
        return self.rank_results(words, result)

    def _count_idf(self, N, n):
        res = math.log((N - n + 0.5) * 1.0 / (n + 0.5))
        if res < 0:
            res = EPS
        return res

    def doc_phrase_weight(self, words_positions):
        for word in words_positions.keys():
            words_positions[word] = [int(x) for x in words_positions[word]]

        words_positions_pointers = {}
        for word in words_positions.keys():
            words_positions_pointers[word] = 0

        words = words_positions.keys()    
        words_count = len(words)

        result_length = 0

        for i in range(0, words_count - 1):

            current_word = words[i]
            while words_positions_pointers[current_word] < len(words_positions[current_word]):            

                last_position = words_positions[current_word][words_positions_pointers[current_word]] 

                j = i + 1
                while j < words_count:
                    next_word = words[j]
                    positions = words_positions[next_word]
                    position_pointer = words_positions_pointers[next_word]
                    while (position_pointer < len(positions) - 1 and positions[position_pointer] < last_position):
                        position_pointer += 1

                    if positions[position_pointer] == str(last_position + 1):
                        result_length += 1
                        last_position += 1
                        
                        if len(words_positions[next_word]) <= position_pointer:
                            break
                        
                        words_positions_pointers[next_word] = position_pointer
                        j += 1
                    else:
                        break
                    last_position = words_positions[next_word][words_positions_pointers[next_word]]

                words_positions_pointers[current_word] += 1

        return result_length

    def rank_results(self, words, urls):
        # import pdb; pdb.set_trace()
        scores = {}
        N = Page.objects.count()
        k1 = 2.0
        b = 0.75
        avg = Page.objects.all().aggregate(Avg('number_of_words'))
        average_size_of_document = int(avg['number_of_words__avg'])
        for url in urls:
            score = 0.0
            words_positions = {}
            for w in words:
                word = Word.objects.get(value=w)
                n = word.pages.count()
                idf = self._count_idf(N, n)
                page = Page.objects.get(url=url)
                number_of_words_on_page = page.number_of_words
                current_word_positions = Match.objects.get(page=page, word=word).positions.split()
                number_of_occurrences = len(current_word_positions)
                words_positions[word] = current_word_positions
                frequency = number_of_occurrences * 1.0 / number_of_words_on_page
                r = frequency * (k1 + 1) / (frequency + \
                    k1 * (1 - b + b * number_of_words_on_page * 1.0 \
                    / average_size_of_document))
                score += r * idf

            doc_phrase_weight = self.doc_phrase_weight(words_positions)

            scores[url] = doc_phrase_weight*1000 + score*999
        # Now we have bm25 for all documents
        sorted_by_score_urls = sorted(scores.items(), key=operator.itemgetter(1),
                                    reverse=True)
        print sorted_by_score_urls
        res = []
        for i in sorted_by_score_urls:
            res.append(i[0])
        return res
